
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
S3ReservationsStorage.add_reservations must merge into agent_spec["metadata"]
rather than replace it, so user-authored keys (description, tags, etc.)
survive the round-trip.
"""
from typing import Any
from typing import Dict

import pytest

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestUserAuthoredMetadata(S3ReservationsStorageTestBase):
    """
    Real registry entries (e.g. neuro_san/registries/copy_cat.hocon) ship
    with their own metadata.description and metadata.tags. The storage
    must preserve those keys when injecting its own reservation/stored_at.
    """

    @pytest.mark.asyncio
    async def test_add_does_not_clobber_user_authored_metadata(self):
        """
        When the input agent_spec already has a user-authored 'metadata'
        dict, add_reservations must merge its own 'reservation' and
        'stored_at' entries into that dict rather than replacing it. After
        the round-trip, the user keys must still be present alongside the
        storage-injected keys.

        Regression guard: a future change that did
            agent_spec["metadata"] = new_metadata
        instead of
            agent_spec["metadata"].update(new_metadata)
        would silently drop user-authored metadata in production.
        """
        # New reservation id (the round-trip test reserved -0001).
        reservation_id = "copy_cat-test-UUID-0002"
        agent_spec_name = "copy_cat"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)
        agent_spec = self._make_agent_spec(agent_spec_name)
        # Pre-populate metadata as a real registry entry would, mirroring
        # neuro_san/registries/copy_cat.hocon. Capturing the values up front
        # so the assertions below compare against the originals (and so a
        # future maintainer can't accidentally read the post-merge dict by
        # going through the same agent_spec reference).
        original_description = (
            "Simple agent network demonstrating use of temporary agent "
            "networks using Reservations."
        )
        original_tags = ["example", "reservations"]
        agent_spec["metadata"] = {
            "description": original_description,
            "tags": original_tags,
        }

        # Write
        await self.storage.add_reservations({reservation: agent_spec})

        # Read
        _, returned_network = self.storage.get_one_reservation(reservation_id)
        returned_metadata: Dict[str, Any] = \
            returned_network.get_config().get("metadata")

        self.assertIsNotNone(
            returned_metadata,
            "metadata block missing from the agent spec returned by "
            "get_one_reservation; the storage's metadata injection wiped "
            "the dict instead of merging into it.",
        )

        # User-authored keys survived the merge.
        self.assertEqual(
            original_description,
            returned_metadata.get("description"),
            "User-authored metadata['description'] was clobbered by the "
            "storage's metadata injection.",
        )
        self.assertEqual(
            original_tags,
            returned_metadata.get("tags"),
            "User-authored metadata['tags'] was clobbered by the storage's "
            "metadata injection.",
        )

        # Storage-injected keys are present alongside the user keys.
        self.assertIn(
            "reservation",
            returned_metadata,
            "Storage-injected metadata['reservation'] is missing after "
            "S3 round-trip; add_reservations did not record the reservation "
            "block on the agent spec.",
        )
        self.assertEqual(
            reservation_id,
            returned_metadata["reservation"].get("id"),
            "metadata['reservation']['id'] does not match the reservation "
            "id that was written.",
        )
        self.assertIn(
            "stored_at",
            returned_metadata,
            "Storage-injected metadata['stored_at'] is missing after S3 "
            "round-trip.",
        )
        self.assertIsInstance(
            returned_metadata["stored_at"],
            float,
            "metadata['stored_at'] is not a float Unix timestamp; the "
            "storage stamped a non-numeric value.",
        )
