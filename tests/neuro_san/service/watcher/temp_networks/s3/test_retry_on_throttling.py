
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
S3ReservationsStorage routes every put_object call through
_do_with_retries. This module exercises the happy retry path: a
transient ThrottlingException on the first attempt is retried, the
retry succeeds, and S3 ends up consistent.
"""
from unittest.mock import patch
import pytest

from botocore.exceptions import ClientError

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestRetryOnThrottling(S3ReservationsStorageTestBase):
    """
    The earlier tests all run against a FakeS3Client that never fails,
    so they never reach the retry branch of _do_with_retries. This test
    fills that gap by injecting a one-shot ThrottlingException on the
    first put_object attempt and verifying the storage retries until
    the put succeeds.
    """

    @pytest.mark.asyncio
    async def test_add_retries_on_throttling_then_succeeds(self):
        """
        On a transient ThrottlingException, add_reservations should
        retry the put_object call. The retry should succeed and S3
        should contain exactly one object at the documented key, with
        no duplicate writes leaked from the failed first attempt.
        """
        reservation_id = "copy_cat-test-UUID-0006"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)
        agent_spec = self._make_agent_spec("copy_cat")

        # Wrap put_object so the FIRST call raises a retryable
        # ThrottlingException, and every subsequent call falls through
        # to the real in-memory store.
        real_put = self.fake_s3.put_object
        call_log = {"count": 0}

        # pylint: disable=invalid-name
        def flaky_put(Bucket, Key, Body, ContentType):
            call_log["count"] += 1
            if call_log["count"] == 1:
                raise ClientError(
                    {
                        "Error": {"Code": "ThrottlingException"},
                        "ResponseMetadata": {"HTTPStatusCode": 503},
                    },
                    "PutObject",
                )
            return real_put(
                Bucket=Bucket,
                Key=Key,
                Body=Body,
                ContentType=ContentType,
            )

        self.fake_s3.put_object = flaky_put

        # Skip the real exponential-backoff sleep so the test stays
        # fast. Patches the module-local asyncio.sleep symbol that
        # _do_with_retries uses.
        with patch(
            "neuro_san.service.watcher.temp_networks.aws_async_client_worker.async_sleep"
        ):
            await self.storage.add_reservations({reservation: agent_spec})

        # put_object was invoked exactly twice: once that threw, once
        # that succeeded. Catches "no retry happened" (count == 1) and
        # "over-retried beyond what we expect" (count > 2).
        self.assertEqual(
            2,
            call_log["count"],
            f"Expected exactly 2 put_object attempts (1 throttled + "
            f"1 retry that succeeded); got {call_log['count']}.",
        )

        # Exactly one S3 object survives. Catches a leaked duplicate
        # from the throttled attempt or the retry.
        self.assertEqual(
            1,
            len(self.fake_s3.objects),
            f"Expected exactly one S3 object after retry; bucket has "
            f"{list(self.fake_s3.objects)}.",
        )

        # That one object is at the documented key (prefix + id +
        # ".json"). Final round-trip-style sanity check.
        expected_key = f"reservations/{reservation_id}.json"
        self.assertIn(
            expected_key,
            self.fake_s3.objects,
            f"Expected S3 object at {expected_key!r}, found "
            f"{list(self.fake_s3.objects)}.",
        )
