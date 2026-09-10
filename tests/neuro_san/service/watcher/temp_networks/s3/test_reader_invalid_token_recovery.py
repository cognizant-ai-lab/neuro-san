
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
from typing import Any
from typing import Dict

from unittest.mock import patch

from botocore.exceptions import ClientError

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase
from tests.neuro_san.service.watcher.temp_networks.s3.fake_s3_client import FakeS3Client


def _make_client_error(code: str, operation_name: str = "GetObject") -> ClientError:
    """
    Build a ClientError carrying the given S3 error code, shaped the way
    boto3 surfaces credential rejections (HTTP 400 with a parsed body code).
    """
    return ClientError(
        {
            "Error": {
                "Code": code,
                "Message": f"{code} (test)",
            },
            "ResponseMetadata": {"HTTPStatusCode": 400},
        },
        operation_name,
    )


class _InvalidTokenClient:
    """
    Wraps the in-memory FakeS3Client with a client-construction-time
    credential state: a client built while the state is bad rejects every
    request with InvalidToken (as real S3 does when a request is signed
    with a malformed/mismatched token), and a client built after the
    credential chain re-resolved delegates normally.
    """

    # pylint: disable=too-few-public-methods

    def __init__(self, fake_s3: FakeS3Client, bad: bool):
        self._fake_s3: FakeS3Client = fake_s3
        self._bad: bool = bad

    # pylint: disable=invalid-name
    def get_object(self, Bucket: str, Key: str) -> Dict[str, Any]:
        """
        Reject with InvalidToken while this client's credential state is
        bad; otherwise delegate to the fake.
        """
        if self._bad:
            raise _make_client_error("InvalidToken")
        return self._fake_s3.get_object(Bucket=Bucket, Key=Key)


class TestReaderInvalidTokenRecovery(S3ReservationsStorageTestBase):
    """
    Verifies that a read hitting InvalidToken rebuilds the session +
    client and succeeds, instead of reporting the reservation as
    not-found until a process restart (the neuro-san-studio #1310
    failure mode).
    """

    def test_invalid_token_triggers_rebuild_and_read_succeeds(self):
        """
        Scenario: the reader's client was built from a bad credential
        state (e.g. captured mid-rotation), so its first GET fails with
        InvalidToken; the re-resolved credential chain behind the SECOND
        client construction is healthy.

        Expected: the widened gate routes InvalidToken through the same
        reset-and-retry path as ExpiredToken, so the read returns the
        reservation. If InvalidToken is not gated (the pre-widening
        behavior), the error propagates to the reader's log-and-continue
        handler and this test fails with a (None, None) read after a
        single client construction.
        """
        reservation_id: str = self._put_live_reservation("copy_cat-invalid-token")

        credential_state = {"bad": True}
        creations = {"count": 0}

        def create_client_with_recovery(*_args, **_kwargs) -> _InvalidTokenClient:
            creations["count"] += 1
            if creations["count"] >= 2:
                # The retry's reset discarded the session; the re-resolved
                # chain behind this second construction is healthy.
                credential_state["bad"] = False
            return _InvalidTokenClient(self.fake_s3, credential_state["bad"])

        # sync_sleep is patched so the retry's jittered backoff does not
        # slow the test down; recovery behavior is unaffected.
        with self._fresh_reader_client(create_client_with_recovery), patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.sync_sleep"
        ):
            reservation, agent_network = self.storage.get_one_reservation(reservation_id)

        self.assertIsNotNone(
            reservation,
            "Expected the read to recover from InvalidToken by rebuilding the "
            "session + client. A None reservation means the error was logged and "
            "swallowed instead - the #1310 failure mode, where the bad credential "
            "state persists and every read of the network reports it not-found.",
        )
        self.assertIsNotNone(agent_network)
        self.assertGreaterEqual(
            creations["count"], 2,
            f"Expected at least 2 client constructions (the failing client plus "
            f"the rebuild after InvalidToken reached the credential-rejection "
            f"gate); got {creations['count']}. A single construction means the "
            f"gate never fired.",
        )
