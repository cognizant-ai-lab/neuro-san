
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
Pins the expiration sweep's recovery from AWS credentials expiring
MID-sweep - after the listing succeeded but before the per-object
get/delete calls complete.

When this can happen: AwsSyncClientWorker's long-lived client is
keyless, so token-based credentials (IAM Instance Roles, ECS Task
Roles, SSO) refresh at signing time and cannot expire mid-sweep. What
CAN still be rejected mid-sweep are STATIC credentials rotated
externally - env vars or a credentials file rewritten by another
process - which botocore resolves once per Session and never re-reads
on its own. The only recovery mechanism for those is reactive:
retry_with_new_client() wraps the whole sweep, and when an ExpiredToken
ClientError reaches it, it discards the session + client and re-runs
the sweep with a freshly resolved credential chain.

The failure mode this test guards against: if ExpiredToken errors
raised by the per-object get_object calls are caught by
expire_one_reservation's broad except-ClientError handler and merely
logged, the wrapper never sees them, so credentials are never
refreshed, every remaining key in the sweep makes exactly one doomed
S3 call, NOTHING is expired, and expire_reservations() returns as if
it succeeded. Expired reservations silently linger until a later
sweep's list_objects_v2 call happens to fail outside the swallowing
handler.
"""
import json
import time

from unittest.mock import patch

from botocore.exceptions import ClientError

from tests.neuro_san.service.watcher.temp_networks.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestExpirationCredentialExpiryMidSweep(S3ReservationsStorageTestBase):
    """
    Verifies that when the S3 token expires between the listing and the
    per-object operations, the sweep refreshes credentials (by building
    a new client) and still expires every expired reservation, rather
    than reporting success while doing nothing.
    """

    def _put_expired_reservation(self, reservation_id: str) -> str:
        """
        Place a well-formed, already-expired reservation object directly
        into the fake bucket (bypassing the writer, as if written by an
        earlier process whose lease has since lapsed).

        :return: the S3 object key used
        """
        key: str = f"reservations/{reservation_id}.json"
        self.fake_s3.objects[key] = json.dumps({
            "name": reservation_id,
            "metadata": {
                "reservation": {
                    "id": reservation_id,
                    "lifetime_in_seconds": 3600.0,
                    # One hour in the past: unambiguously expired.
                    "expiration_time_in_seconds": time.time() - 3600.0,
                },
                "stored_at": time.time() - 7200.0,
            },
        }).encode("utf-8")
        return key

    def test_mid_sweep_expired_token_refreshes_credentials_and_completes(self):
        """
        Scenario: the sweep's client was built from a token that S3
        rejects by the time the per-object get_object calls run.

        Simulation:
          * get_object raises ClientError(ExpiredToken) while the
            token_state flag is set (it starts True).
          * Session.create_client is re-patched so that the SECOND
            client built under this test's patch "refreshes" the token
            (flips the flag) - modeling production, where
            retry_with_new_client discards the session + client and the
            re-resolved credential chain hands back a fresh token.

        Expected: the ExpiredToken propagates out of the per-object
        handling to retry_with_new_client, which rebuilds the client and
        re-runs the sweep; every expired reservation is deleted.

        If expire_one_reservation swallows the ExpiredToken per key
        instead of re-raising it, both assertions fail: the client is
        never rebuilt and all three expired objects remain while the
        sweep reports success.
        """
        expired_keys = [
            self._put_expired_reservation(f"copy_cat-expired-{index}")
            for index in range(3)
        ]

        # --- simulate a token that has expired for the first client -------
        # Mutable holder (not an instance attribute) so the two closures
        # below can share and flip the flag.
        token_state = {"expired": True}
        real_get_object = self.fake_s3.get_object

        # pylint: disable=invalid-name
        def get_object_with_expiring_token(Bucket: str, Key: str):
            """Raise ExpiredToken exactly as boto3 surfaces it (HTTP 400)."""
            if token_state["expired"]:
                raise ClientError(
                    {
                        "Error": {
                            "Code": "ExpiredToken",
                            "Message": "The provided token has expired.",
                        },
                        "ResponseMetadata": {"HTTPStatusCode": 400},
                    },
                    "GetObject",
                )
            return real_get_object(Bucket=Bucket, Key=Key)

        # Inject onto the in-memory FakeS3Client for the duration of this
        # test only (instance attribute shadows the class method).
        self.fake_s3.get_object = get_object_with_expiring_token

        # --- building a second client models the credential refresh -------
        create_client_calls = {"count": 0}

        def create_client_with_refresh(*_args, **_kwargs):
            create_client_calls["count"] += 1
            if create_client_calls["count"] >= 2:
                # The second re-resolution of the credential chain (via
                # retry_with_new_client discarding the session + client)
                # hands back a fresh token that works from here on.
                token_state["expired"] = False
            return self.fake_s3

        # Overrides (stacks on top of) the base class's Session.create_client
        # patch for the duration of this with-block.
        #
        # sync_sleep is patched defensively: ExpiredToken is not in
        # S3Util.is_retryable_client_error's retryable set today, so
        # do_with_retries should not back off on it - but if a regression
        # ever makes it retryable, this keeps the test from sleeping
        # through 8 exponential-backoff retries per object.
        with patch(
            "neuro_san.service.watcher.temp_networks.aws_sync_client_worker.Session.create_client",
            new=create_client_with_refresh,
        ), patch(
            "neuro_san.service.watcher.temp_networks.aws_sync_client_worker.sync_sleep"
        ):
            self.storage.expiration.expire_reservations()

        remaining = [key for key in expired_keys if key in self.fake_s3.objects]
        self.assertEqual(
            [], remaining,
            f"Expected every expired reservation to be deleted after the credential "
            f"refresh; these remain: {remaining}. This means the mid-sweep "
            f"ExpiredToken was swallowed per-object and never reached "
            f"retry_with_new_client, so the sweep 'succeeded' without expiring "
            f"anything.",
        )
        self.assertGreaterEqual(
            create_client_calls["count"], 2,
            f"Expected at least 2 client constructions under this test's patch "
            f"(rebuilds forced by ExpiredToken reaching retry_with_new_client; the "
            f"second rebuild picks up the fresh token); got "
            f"{create_client_calls['count']}. Fewer means the ExpiredToken never "
            f"triggered retry_with_new_client's session + client reset.",
        )
