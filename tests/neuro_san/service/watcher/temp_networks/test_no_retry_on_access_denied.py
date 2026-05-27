
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
S3ReservationsStorage._is_retryable_client_error classifies errors
into retryable (transient: throttling, slow-down, 5xx) and
non-retryable (permanent: AccessDenied, malformed request, etc.).
This module exercises the non-retryable branch: an AccessDenied
ClientError must propagate immediately, with no S3 mutation and
nothing retrievable through the public read path.
"""
from unittest.mock import patch

from botocore.exceptions import ClientError

from tests.neuro_san.service.watcher.temp_networks.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestNoRetryOnAccessDenied(S3ReservationsStorageTestBase):
    """
    Companion to TestRetryOnThrottling. T6 pinned that transient errors
    DO retry; this test pins that AccessDenied does NOT retry. Together
    they document the storage's full retry policy.
    """

    def test_add_does_not_retry_on_access_denied(self):
        """
        On AccessDenied (HTTP 403 with error code AccessDenied -
        what real S3 returns for permission errors), add_reservations
        should propagate the error immediately without any retry, and
        leave nothing in S3 nor anything retrievable through the public
        read path.
        """
        reservation_id = "copy_cat-test-UUID-0007"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)
        agent_spec = self._make_agent_spec("copy_cat")

        # Wrap put_object: every call raises AccessDenied. Status 403
        # is what real S3 returns for permission errors and lands the
        # error on the non-retryable branch of _is_retryable_client_error
        # (AccessDenied is not in retryable_codes; 403 is not 5xx).
        call_log = {"count": 0}

        # pylint: disable=invalid-name,unused-argument
        def denied_put(Bucket, Key, Body, ContentType):
            call_log["count"] += 1
            raise ClientError(
                {
                    "Error": {"Code": "AccessDenied"},
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                },
                "PutObject",
            )

        self.fake_s3.put_object = denied_put

        # Skip backoff sleep defensively. If a regression makes
        # AccessDenied retryable, we don't want the test to hang.
        with patch(
            "neuro_san.service.watcher.temp_networks."
            "s3_reservations_storage.time.sleep"
        ):
            with self.assertRaises(ClientError) as ctx:
                self.storage.add_reservations({reservation: agent_spec})

        # The original error code is preserved on the way up. Catches
        # bugs where the storage swallows or wraps the error in a
        # different exception type, hiding the real cause from callers.
        self.assertEqual(
            "AccessDenied",
            ctx.exception.response["Error"]["Code"],
            "AccessDenied error code was not preserved on propagation; "
            "the original cause is being hidden from callers.",
        )

        # Exactly ONE put_object attempt - no retries fired on a
        # non-retryable error. Catches a regression where AccessDenied
        # is added to retryable_codes (would cost N attempts and N
        # backoff sleeps before the error finally surfaces).
        self.assertEqual(
            1,
            call_log["count"],
            f"Expected exactly 1 put_object attempt for non-retryable "
            f"AccessDenied; got {call_log['count']}. The storage is "
            f"retrying a non-retryable error.",
        )

        # No S3 object was written. Catches a regression where the
        # storage somehow puts a partial object before the error
        # propagates up.
        self.assertEqual(
            0,
            len(self.fake_s3.objects),
            f"Expected empty bucket after AccessDenied; bucket has "
            f"{list(self.fake_s3.objects)}.",
        )

        # The failed reservation is NOT retrievable through the public
        # read path. Confirms end-to-end that nothing leaked into any
        # cache or fallback store: a fresh caller asking for this id
        # gets None, as if the failed write had never happened.
        result_reservation, result_network = \
            self.storage.get_one_reservation(reservation_id)
        self.assertIsNone(
            result_reservation,
            f"get_one_reservation returned a Reservation for "
            f"{reservation_id!r} after AccessDenied; the failed write "
            f"should leave nothing retrievable.",
        )
        self.assertIsNone(
            result_network,
            f"get_one_reservation returned an AgentNetwork for "
            f"{reservation_id!r} after AccessDenied; the failed write "
            f"should leave nothing retrievable.",
        )
