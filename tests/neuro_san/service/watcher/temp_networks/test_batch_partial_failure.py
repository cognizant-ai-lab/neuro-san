
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
S3ReservationsStorage.add_reservations writes batch entries one at a
time in a Python for-loop with no atomic-batch semantics. This module
exercises the partial-failure case: if a later entry's put_object
fails, earlier successful writes remain in S3 (no automatic rollback).
"""
from unittest.mock import patch
import pytest

from botocore.exceptions import ClientError

from tests.neuro_san.service.watcher.temp_networks.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestBatchPartialFailure(S3ReservationsStorageTestBase):
    """
    Pin the current partial-success contract of add_reservations:
    earlier iterations of the for-loop are NOT rolled back when a later
    iteration raises. A future change that introduces atomic-batch
    semantics (rollback on failure) would intentionally break this test
    and require an explicit update, surfacing the contract change in
    code review rather than letting it slip in silently.
    """

    @pytest.mark.asyncio
    async def test_add_preserves_earlier_successes_when_later_entry_fails(self):
        """
        With a batch of 3 reservations where the 3rd put_object raises
        AccessDenied, add_reservations propagates the error and leaves
        the 1st and 2nd writes intact in S3. The 3rd entry's key is not
        in S3 (its put failed before any S3 mutation).
        """
        # Three reservation ids; iteration order matches insertion order
        # in the dict literal below (Python 3.7+ guaranteed).
        res_a = self._make_reservation("copy_cat-test-UUID-0008a", lifetime_seconds=600.0)
        res_b = self._make_reservation("copy_cat-test-UUID-0008b", lifetime_seconds=1200.0)
        res_c = self._make_reservation("copy_cat-test-UUID-0008c", lifetime_seconds=1800.0)

        # Distinct model_names per spec - if a future bug merges specs
        # across iterations, the surviving objects would carry the wrong
        # model_name and a follow-up read could surface that.
        spec_a = self._make_agent_spec("copy_cat")
        spec_a["llm_config"]["model_name"] = "gpt-4o"
        spec_b = self._make_agent_spec("copy_cat")
        spec_b["llm_config"]["model_name"] = "claude-3-5-sonnet"
        spec_c = self._make_agent_spec("copy_cat")
        spec_c["llm_config"]["model_name"] = "gemini-2.0-flash"

        # Wrap put_object: only the 3rd call raises AccessDenied;
        # iterations 1 and 2 fall through to the real in-memory store.
        # Status 403 lands the error on the non-retryable branch of
        # _is_retryable_client_error so we know the failure is final.
        real_put = self.fake_s3.put_object
        # Defensively restore put_object on the fake at end-of-test. The
        # base class hands each test a fresh FakeS3Client in setUp, so
        # this is a no-op today; the cleanup is here to document intent
        # and to keep the test correct if a future refactor turns
        # self.fake_async_s3 into a shared object.
        self.addCleanup(setattr, self.fake_async_s3, "put_object", real_put)
        call_log = {"count": 0}
        template_error = ClientError(
            {
                "Error": {"Code": "AccessDenied"},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "PutObject",
        )

        # pylint: disable=invalid-name
        def fail_on_third(Bucket, Key, Body, ContentType):
            call_log["count"] += 1
            if call_log["count"] == 3:
                raise template_error

            return real_put(
                Bucket=Bucket,
                Key=Key,
                Body=Body,
                ContentType=ContentType,
            )

        self.fake_s3.put_object = fail_on_third

        # Skip backoff sleep defensively. AccessDenied is non-retryable
        # so no sleep should fire, but we patch it so a regression that
        # adds AccessDenied to retryable_codes does not hang the test.
        with patch(
            "neuro_san.service.watcher.temp_networks.s3_reservations_storage.asyncio.sleep"
        ):

            with self.assertRaises(ClientError) as ctx:
                await self.storage.add_reservations(
                    {res_a: spec_a, res_b: spec_b, res_c: spec_c}
                )

        # The original AccessDenied error code propagates. Catches a
        # bug where the storage swallows the error or wraps it in a
        # different exception type.
        self.assertEqual(
            "AccessDenied",
            ctx.exception.response["Error"]["Code"],
            "AccessDenied error code was not preserved on propagation.",
        )

        # Exactly 3 put attempts: 2 successful, 1 that failed. Catches
        # bugs where the loop continues past the failure (count > 3) or
        # stops early before the third entry (count < 3).
        self.assertEqual(
            3,
            call_log["count"],
            f"Expected exactly 3 put_object attempts (2 succeeded + 1 "
            f"failed); got {call_log['count']}.",
        )

        # The two earlier successes survive in S3. Catches:
        # - rollback regression: bucket would be empty
        # - leaked third write: bucket would contain res_c's key
        # - cross-contamination: extra/wrong keys present
        expected_surviving = {
            f"reservations/{res_a.get_reservation_id()}.json",
            f"reservations/{res_b.get_reservation_id()}.json",
        }
        self.assertEqual(
            expected_surviving,
            set(self.fake_s3.objects),
            f"Expected the two earlier successes to survive in S3, got "
            f"{list(self.fake_s3.objects)}. The storage is rolling back "
            f"earlier writes or leaking the failed write.",
        )

        # Belt-and-suspenders: the failed entry's key is NOT in S3.
        # Redundant with the set assertion above but reads as the
        # intended contract on its own and gives a clear failure
        # message if a partial write leaks just the failed key.
        self.assertNotIn(
            f"reservations/{res_c.get_reservation_id()}.json",
            self.fake_s3.objects,
            f"Failed entry's key leaked into S3; bucket has "
            f"{list(self.fake_s3.objects)}.",
        )
