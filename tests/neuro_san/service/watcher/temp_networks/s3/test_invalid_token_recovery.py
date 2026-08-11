
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
Pins recovery from S3 rejecting a request's session token as
InvalidToken ("The provided token is malformed or otherwise invalid")
on the reservation READ path.

Motivation - a real production failure (neuro-san-studio issue #1310,
"AND is sporadically broken"):

    S3ReservationsReader: S3 error processing reservation object <id>
    during sync: An error occurred (InvalidToken) when calling the
    GetObject operation: The provided token is malformed or otherwise
    invalid.

The user-visible symptom was a network that had just been created
coming back "not found" (404): the reader's ClientError handler logged
the credential error and reported the reservation as missing, even
though the object was written to S3 just fine. It looked sporadic
because the pod that created the network still served it from memory,
while every other pod had to read S3 and failed.

Root cause: the worker's cached frozen-credential snapshot went stale,
S3 rejected it with InvalidToken - but the credential-retry gate
matched only ExpiredToken, so the snapshot was never invalidated and
every read kept failing until a pod restart.

The widened gate (S3Util.is_credential_rejection_error) treats
InvalidToken (and TokenRefreshRequired) like ExpiredToken: discard the
cached snapshot, re-resolve credentials, and retry. Without the
widening, the recovery test below fails with get_one_reservation()
returning (None, None) after a single credential resolution - the
exact #1310 failure mode.
"""
import json
import time

from typing import Any
from typing import Dict

from unittest import TestCase
from unittest.mock import patch

from botocore.credentials import Credentials
from botocore.exceptions import ClientError

from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util
from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


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


class TestCredentialRejectionGate(TestCase):
    """
    Pins the boundaries of S3Util.is_credential_rejection_error: which
    error codes trigger a credential reset + retry, and which are
    deliberately left to surface.
    """

    def test_codes_that_trigger_re_resolution(self):
        """
        Expired, malformed/mismatched, and refresh-required token codes
        must trigger a credential reset: each means the cached credential
        state is bad, and re-resolving it is the only remedy.
        """
        for code in ("ExpiredToken", "ExpiredTokenException", "InvalidToken", "TokenRefreshRequired"):
            with self.subTest(code=code):
                self.assertTrue(
                    S3Util.is_credential_rejection_error(_make_client_error(code)),
                    f"Expected {code} to trigger credential re-resolution.",
                )

    def test_codes_that_must_surface(self):
        """
        Rotated long-lived key pairs and signing problems must NOT be
        retried: re-resolution cannot fix them, and retrying would mask
        genuine misconfiguration.
        """
        for code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied", "NoSuchKey"):
            with self.subTest(code=code):
                self.assertFalse(
                    S3Util.is_credential_rejection_error(_make_client_error(code)),
                    f"Expected {code} NOT to trigger credential re-resolution.",
                )


class TestReaderInvalidTokenRecovery(S3ReservationsStorageTestBase):
    """
    Verifies that a read hitting InvalidToken resets the cached frozen
    credentials, re-resolves, and succeeds - instead of reporting the
    reservation as not-found until a process restart (the
    neuro-san-studio #1310 failure mode).
    """

    def _put_live_reservation(self, reservation_id: str) -> str:
        """
        Place a well-formed, unexpired reservation object directly into
        the fake bucket (matching the writer's on-disk schema, bypassing
        the writer) so the read path has something real to fetch.

        :return: the reservation id (readers derive the S3 key from it)
        """
        spec: Dict[str, Any] = {
            "name": reservation_id,
            "llm_config": {"model_name": "gpt-5.2"},
            "tools": [{"name": reservation_id, "function": {"description": "test frontman"}}],
            "metadata": {
                "reservation": {
                    "id": reservation_id,
                    "lifetime_in_seconds": 3600.0,
                    "expiration_time_in_seconds": time.time() + 3600.0,
                },
                "stored_at": time.time(),
            },
        }
        self.fake_s3.objects[f"reservations/{reservation_id}.json"] = \
            json.dumps(spec).encode("utf-8")
        return reservation_id

    def test_invalid_token_triggers_credential_reset_and_read_succeeds(self):
        """
        Scenario: the worker's cached frozen-credential snapshot has gone
        stale (e.g. captured mid-rotation), so requests signed with it
        are rejected with InvalidToken; the snapshot re-frozen after the
        retry's reset is healthy.

        Expected: the widened gate routes InvalidToken through the same
        reset-and-retry path as ExpiredToken, so the read returns the
        reservation. If InvalidToken is not gated (the pre-fix behavior),
        the error propagates to the reader's log-and-continue handler and
        this test fails with a (None, None) read after a single
        credential resolution.
        """
        reservation_id: str = self._put_live_reservation("copy_cat-invalid-token")

        resolutions = {"count": 0}

        def counting_get_credentials(*_args, **_kwargs) -> Credentials:
            # Overrides the base class's Session.get_credentials patch
            # (same target) so the test can observe each re-resolution.
            resolutions["count"] += 1
            return Credentials("bogus", "bogus")

        real_get_object = self.fake_s3.get_object

        # pylint: disable=invalid-name
        def get_object_rejecting_stale_snapshot(Bucket: str, Key: str) -> Dict[str, Any]:
            if resolutions["count"] < 2:
                # Requests signed with the first (stale) snapshot are
                # rejected; the snapshot re-frozen after the retry's
                # reset works.
                raise _make_client_error("InvalidToken")
            return real_get_object(Bucket=Bucket, Key=Key)

        self.fake_s3.get_object = get_object_rejecting_stale_snapshot
        self.addCleanup(setattr, self.fake_s3, "get_object", real_get_object)

        with patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.Session.get_credentials",
            new=counting_get_credentials,
        ):
            # The worker freezes credentials lazily, so the first
            # resolution happens inside this read.
            reservation, agent_network = self.storage.get_one_reservation(reservation_id)

        self.assertIsNotNone(
            reservation,
            "Expected the read to recover from InvalidToken by resetting the "
            "cached frozen credentials. A None reservation means the error was "
            "logged and swallowed instead - the #1310 failure mode, where the "
            "stale snapshot persists and every read of the network reports it "
            "not-found (404) until a pod restart.",
        )
        self.assertIsNotNone(agent_network)
        self.assertGreaterEqual(
            resolutions["count"], 2,
            f"Expected at least 2 credential resolutions (the stale snapshot "
            f"plus the re-resolution after InvalidToken reached the "
            f"credential-rejection gate); got {resolutions['count']}. A single "
            f"resolution means the gate never fired.",
        )
