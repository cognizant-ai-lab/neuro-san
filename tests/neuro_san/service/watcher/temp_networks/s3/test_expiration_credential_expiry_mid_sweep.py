
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

Why this scenario exists at all: AwsSyncClientWorker creates its boto
clients from FROZEN credentials (explicit key/secret/token passed to
create_client), which disables botocore's native at-signing-time
auto-refresh. The only recovery mechanism is therefore reactive:
retry_with_new_client() wraps the whole sweep, and when an ExpiredToken
ClientError reaches it, it resets the cached frozen credentials and
re-runs the sweep with a freshly built client. Token-based credentials
(IAM Instance Roles, ECS Task Roles, SSO) expire on the order of an
hour, so a long sweep over a large bucket can realistically outlive its
token.

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

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
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
          * get_object raises ClientError(ExpiredToken) while the FIRST
            client is in use (self.token_expired starts True).
          * Session.create_client is re-patched so that building a
            SECOND client "refreshes" the token (flips the flag) - which
            is exactly what happens in production when
            retry_with_new_client resets frozen_credentials and the
            credential chain hands back a fresh token.

        Expected: the ExpiredToken propagates out of the per-object
        handling to retry_with_new_client, which builds client #2 and
        re-runs the sweep; every expired reservation is deleted.

        If expire_one_reservation swallows the ExpiredToken per key
        instead of re-raising it, both assertions fail: only one client
        is ever created and all three expired objects remain while the
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
                # retry_with_new_client reset frozen_credentials and built a
                # new client: the fresh token works from here on.
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
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.Session.create_client",
            new=create_client_with_refresh,
        ), patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.sync_sleep"
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
            f"Expected at least 2 clients (initial + rebuilt-after-refresh); got "
            f"{create_client_calls['count']}. A single client means the ExpiredToken "
            f"never triggered retry_with_new_client's credential reset.",
        )
