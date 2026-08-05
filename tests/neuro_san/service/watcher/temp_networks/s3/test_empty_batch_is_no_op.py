
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
S3ReservationsStorage.add_reservations should be a complete no-op
when called with an empty mapping. Real callers may legitimately
pass {} when pre-filtering yields no new reservations; the storage
must handle that without crashing, without writing placeholder
objects, and without making any S3 calls.
"""
import pytest

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestEmptyBatchIsNoOp(S3ReservationsStorageTestBase):
    """
    The empty-batch contract: add_reservations({}) is equivalent to
    not calling add_reservations at all. No exception, no S3 call, no
    bucket mutation. Existing tests T1-T8 all use N>=1 entries, so
    none of them touch this path.
    """

    @pytest.mark.asyncio
    async def test_add_with_empty_dict_is_a_no_op(self):
        """
        add_reservations({}) returns normally, makes zero put_object
        calls, and leaves the bucket exactly as it was. Catches
        regressions where empty input crashes (KeyError, IndexError,
        StopIteration) or silently writes placeholder entries.
        """
        # Wrap put_object so we can count attempts. Real put still
        # works for any incidental call (which there should be zero of).
        real_put = self.fake_s3.put_object
        call_log = {"count": 0}

        def counting_put(**kwargs):
            call_log["count"] += 1
            return real_put(**kwargs)

        self.fake_s3.put_object = counting_put

        # The bucket starts empty; record that as the precondition we
        # expect to remain unchanged.
        self.assertEqual(
            0,
            len(self.fake_s3.objects),
            "Precondition violated: bucket should start empty.",
        )

        # The call should return normally - no exception. If this
        # raises, the no-op contract is broken and the call site needs
        # defensive guards it should not need.
        await self.storage.add_reservations({})

        # No put_object call was made. Catches a regression where the
        # storage attempts to write a placeholder for an empty input,
        # or where empty-input handling falls through into the loop
        # body with sentinel data.
        self.assertEqual(
            0,
            call_log["count"],
            f"Expected zero put_object calls for empty input; got "
            f"{call_log['count']}. The storage is making S3 traffic "
            f"for an empty batch.",
        )

        # The bucket is still empty - end-to-end check that no S3
        # mutation occurred. Redundant with the call-count check above
        # but reads as the user-facing contract on its own.
        self.assertEqual(
            0,
            len(self.fake_s3.objects),
            f"Expected empty bucket after empty-input call; bucket has "
            f"{list(self.fake_s3.objects)}.",
        )
