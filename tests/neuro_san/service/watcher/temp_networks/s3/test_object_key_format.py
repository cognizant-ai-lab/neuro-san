
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
S3ReservationsStorage.add_reservations writes each reservation to a
specific S3 object key. This module pins that key format as a contract.
"""
import pytest

from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestObjectKeyFormat(S3ReservationsStorageTestBase):
    """
    The S3 object key written by add_reservations follows the documented
    format "{prefix}{reservation_id}.json". A refactor that changes the
    layout (e.g., to "{prefix}{id}/data.json") would still let the
    round-trip test pass because read and write both go through the same
    helper. This test pins the observable contract from the outside by
    asserting against a hardcoded literal path.
    """

    @pytest.mark.asyncio
    async def test_add_writes_at_expected_object_key(self):
        """
        After add_reservations, the S3 bucket contains exactly one object,
        and that object's key matches the documented "{prefix}{id}.json"
        format. The write-side path and the read-side helper agree on the
        same key.
        """
        # New reservation id; -0001 through -0003 are reserved by the
        # earlier tests.
        reservation_id = "copy_cat-test-UUID-0004"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)
        agent_spec = self._make_agent_spec("copy_cat")

        # Write
        await self.storage.add_reservations({reservation: agent_spec})

        # Hardcoded literal of the expected path. Constructing this from
        # the storage's own helper would defeat the purpose of pinning
        # the format - a refactored helper would silently match a
        # refactored writer. The prefix "reservations/" is configured in
        # S3ReservationsStorageTestBase.setUp; the per-reservation suffix "{id}.json" is
        # the documented layout.
        expected_key = f"reservations/{reservation_id}.json"

        # Exactly one object exists, at exactly the expected path. This
        # single assertion catches several unrelated bugs:
        #   * wrong prefix (e.g., "reserve_/")
        #   * missing or different suffix (e.g., no ".json", or ".dat")
        #   * extra slash between prefix and id ("reservations//id.json")
        #   * a leaked second blob written under a sibling key
        self.assertEqual(
            [expected_key],
            list(self.fake_s3.objects),
            f"Expected exactly one S3 object at {expected_key!r}, got "
            f"{list(self.fake_s3.objects)}",
        )

        # The read-side helper produces the same key the writer used.
        # Guards against the read and write paths drifting out of sync
        # (e.g., the writer is refactored but the helper is not).
        self.assertEqual(
            expected_key,
            S3Util.get_obj_key_for_reservation(self.storage.writer.prefix, reservation_id),
            "get_obj_key_for_reservation does not produce the same key "
            "the storage wrote to; read and write would disagree.",
        )
