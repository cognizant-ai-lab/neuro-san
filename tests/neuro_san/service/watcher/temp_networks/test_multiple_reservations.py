
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
S3ReservationsStorage.add_reservations accepts a dict of multiple
{Reservation: agent_spec} pairs. This module exercises the for-loop
that iterates over those pairs.
"""
import pytest

from tests.neuro_san.service.watcher.temp_networks.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestMultipleReservations(S3ReservationsStorageTestBase):
    """
    Verify that a single add_reservations call with N>1 entries writes
    one S3 object per entry and preserves each spec independently. The
    other tests (#1, #3) only exercise N=1 per call, so the for-loop
    body is never iterated more than once. This test fills that gap.
    """

    @pytest.mark.asyncio
    async def test_add_writes_each_reservation_independently(self):
        """
        One call to add_reservations({r1: s1, r2: s2, r3: s3}) writes
        three distinct S3 objects, one per reservation, each with the
        spec it was paired with. No cross-contamination between
        iterations of the for-loop in add_reservations.
        """
        # Three reservation ids; -0001 .. -0004 are reserved by earlier
        # tests. Use -0005a/b/c so the suffix unambiguously belongs to
        # this test if a future bug leaves orphans behind.
        res_a = self._make_reservation("copy_cat-test-UUID-0005a", lifetime_seconds=600.0)
        res_b = self._make_reservation("copy_cat-test-UUID-0005b", lifetime_seconds=1200.0)
        res_c = self._make_reservation("copy_cat-test-UUID-0005c", lifetime_seconds=1800.0)

        # Each spec carries a distinct model_name so we can prove later
        # that each id reads back with its own spec, not a sibling's.
        spec_a = self._make_agent_spec("copy_cat")
        spec_a["llm_config"]["model_name"] = "gpt-4o"
        spec_b = self._make_agent_spec("copy_cat")
        spec_b["llm_config"]["model_name"] = "claude-3-5-sonnet"
        spec_c = self._make_agent_spec("copy_cat")
        spec_c["llm_config"]["model_name"] = "gemini-2.0-flash"

        # Single batch call - the entire interaction with the storage.
        await self.storage.add_reservations(
            {res_a: spec_a, res_b: spec_b, res_c: spec_c}
        )

        # All three S3 objects exist, each at its own documented key.
        # Catches off-by-one bugs (only first/last entry written) and
        # any iteration that skips entries (e.g., stride bug).
        expected_keys = {
            f"reservations/{res_a.get_reservation_id()}.json",
            f"reservations/{res_b.get_reservation_id()}.json",
            f"reservations/{res_c.get_reservation_id()}.json",
        }
        self.assertEqual(
            expected_keys,
            set(self.fake_s3.objects),
            f"Expected three distinct S3 keys, got "
            f"{list(self.fake_s3.objects)}",
        )

        # Each reservation reads back with its OWN model_name. Catches
        # cross-contamination bugs where one iteration of the for-loop
        # leaks state into the next (e.g., metadata accumulating across
        # entries because the input dict reference is shared).
        _, network_a = self.storage.get_one_reservation(res_a.get_reservation_id())
        _, network_b = self.storage.get_one_reservation(res_b.get_reservation_id())
        _, network_c = self.storage.get_one_reservation(res_c.get_reservation_id())

        self.assertEqual(
            "gpt-4o",
            network_a.get_config()["llm_config"]["model_name"],
            "Spec for res_a did not survive the batch write; was "
            "overwritten or cross-contaminated by another iteration.",
        )
        self.assertEqual(
            "claude-3-5-sonnet",
            network_b.get_config()["llm_config"]["model_name"],
            "Spec for res_b did not survive the batch write; was "
            "overwritten or cross-contaminated by another iteration.",
        )
        self.assertEqual(
            "gemini-2.0-flash",
            network_c.get_config()["llm_config"]["model_name"],
            "Spec for res_c did not survive the batch write; was "
            "overwritten or cross-contaminated by another iteration.",
        )
