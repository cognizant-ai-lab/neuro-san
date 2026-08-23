
# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT
"""
Pins credential recovery on the reservation WRITE path: a deployment
batch whose first attempt fails against a bad credential state must
discard the shared AioSession, re-resolve the chain behind a fresh
session, retry, and land the write - not lose the batch.

A lost batch is the worst credential failure mode this storage has:
add_reservations raises, the updater logs and drops the item (there is
no requeue), and other pods then report the just-created network
not-found. Covered here for both faces of a rotation window:

  * InvalidToken - S3 rejects the request the batch's client signed
    with a bad resolved credential state (a ClientError; the same
    production failure the reader-path test in
    test_invalid_token_recovery.py pins, see neuro-san-studio #1310).
  * NoCredentialsError - the chain behind the batch's fresh client
    resolved to nothing (credentials file caught empty mid-rewrite),
    raised locally by botocore at request-signing time. This is a
    BotoCoreError, NOT a ClientError: under a ClientError-only retry
    gate it escapes with retry budget unused and the batch is lost -
    the recovery test below fails exactly that way against such a gate.
"""
from typing import Any
from typing import Dict

from unittest.mock import patch
import pytest

from aiobotocore.session import get_session as real_get_session
from botocore.exceptions import ClientError
from botocore.exceptions import NoCredentialsError

from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util
from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestWriterCredentialRecovery(S3ReservationsStorageTestBase):
    """
    Verifies that the async writer's credential retry discards the
    shared session and completes the batch through a re-resolved chain,
    for both a ClientError rejection (InvalidToken) and a local
    resolution failure (NoCredentialsError).
    """

    async def _run_batch_with_bad_first_session(self, make_error) -> Dict[str, int]:
        """
        Drive one add_reservations batch where every put_object made
        under the FIRST session's credential state raises make_error(),
        and the state heals once the retry has built a SECOND session
        (modeling a rotation that lands between the two resolutions).

        :param make_error: Zero-arg factory for the exception each
                doomed put_object raises.
        :return: Counters: sessions created and put_object attempts.
        """
        reservation = self._make_reservation("copy_cat-test-UUID-cred-rec", lifetime_seconds=600.0)
        spec: Dict[str, Any] = self._make_agent_spec("copy_cat")

        counters = {"sessions": 0, "puts": 0}

        def counting_get_session(*args, **kwargs):
            counters["sessions"] += 1
            return real_get_session(*args, **kwargs)

        real_put = self.fake_s3.put_object

        # pylint: disable=invalid-name
        def put_object_bad_until_second_session(Bucket, Key, Body, ContentType):
            counters["puts"] += 1
            if counters["sessions"] < 2:
                # Still on the first session's bad credential state.
                raise make_error()
            return real_put(Bucket=Bucket, Key=Key, Body=Body, ContentType=ContentType)

        self.fake_s3.put_object = put_object_bad_until_second_session
        self.addCleanup(setattr, self.fake_s3, "put_object", real_put)

        # async_sleep is patched so the credential retry's jittered
        # backoff does not slow the test down; recovery is unaffected.
        with patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_async_client_worker.get_session",
            new=counting_get_session,
        ), patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_async_client_worker.async_sleep"
        ):
            await self.storage.add_reservations({reservation: spec})

        obj_key: str = S3Util.get_obj_key_for_reservation(
            self.PREFIX, reservation.get_reservation_id())
        self.assertIn(
            obj_key, self.fake_s3.objects,
            f"Expected the batch to land in S3 after the credential retry "
            f"rebuilt the session; bucket has {list(self.fake_s3.objects)}. "
            f"A missing key means the batch was lost - other pods would "
            f"report the just-created network not-found.",
        )
        self.assertGreaterEqual(
            counters["sessions"], 2,
            f"Expected at least 2 session creations (the one with the bad "
            f"credential state plus the retry's rebuild); got "
            f"{counters['sessions']}. A single session means the credential "
            f"retry never discarded it.",
        )
        return counters

    @pytest.mark.asyncio
    async def test_invalid_token_triggers_session_rebuild_and_batch_succeeds(self):
        """
        S3 rejects the first attempt's request with InvalidToken (HTTP
        400, non-retryable within do_with_retries): the credential gate
        must discard the session and complete the batch on the retry.
        """
        def make_invalid_token() -> ClientError:
            return ClientError(
                {
                    "Error": {
                        "Code": "InvalidToken",
                        "Message": "The provided token is malformed or otherwise invalid.",
                    },
                    "ResponseMetadata": {"HTTPStatusCode": 400},
                },
                "PutObject",
            )

        await self._run_batch_with_bad_first_session(make_invalid_token)

    @pytest.mark.asyncio
    async def test_empty_chain_triggers_session_rebuild_and_batch_succeeds(self):
        """
        The first attempt's put_object raises NoCredentialsError at
        signing time (empty chain behind that session's client).
        do_with_retries deliberately fast-fails it; the credential
        retry must catch it ALONGSIDE ClientError - it is a
        BotoCoreError - discard the session, and complete the batch.
        Under a ClientError-only gate this test fails with the raw
        NoCredentialsError propagating out of add_reservations.
        """
        await self._run_batch_with_bad_first_session(NoCredentialsError)
