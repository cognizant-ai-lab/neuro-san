
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
import json
import os
import tempfile
from typing import Any
from typing import Dict
from typing import Optional
from unittest import IsolatedAsyncioTestCase

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.reservations.agent_reservation import AgentReservation
from neuro_san.service.watcher.temp_networks.local.local_reservations_storage import LocalReservationsStorage

from tests.neuro_san.internals.network_providers.byok_agent_spec_builder import ByokAgentSpecBuilder
from tests.neuro_san.service.watcher.temp_networks.local.local_reservations_test_helpers \
    import LocalReservationsTestHelpers


class TestLocalReservationsStorage(IsolatedAsyncioTestCase):
    """
    Unit tests for LocalReservationsStorage.

    The constructor, start, expiration and write/read round-trip behaviours are
    currently covered by the sibling test_local_reservations_storage_*.py modules,
    which predate the one-test-module-per-class convention. New tests for this class
    belong here.

    The read path resolves each stored agent spec through NetworkConfigFilterChain
    before building the AgentNetwork.  ExpiringAgentNetworkStorage already resolves
    specs before writing them, but a file written directly (by an older server instance
    during a rolling upgrade, or by other tooling) may still hold a raw spec, and
    get_one_reservation() must hand back the same resolved network either way.
    """

    async def test_get_one_reservation_resolves_raw_spec(self):
        """
        A raw spec written straight to disk comes back with the global sly_data_schema
        merged into the front man, while the file itself is left exactly as written.
        """
        with tempfile.TemporaryDirectory() as base_path:
            storage: LocalReservationsStorage = LocalReservationsStorage(base_path=base_path)
            storage.start()
            reservation: AgentReservation = LocalReservationsTestHelpers.make_reservation(prefix="raw",
                                                                                          lifetime_s=3600.0)
            reservation_id: str = reservation.get_reservation_id()
            # Write through the storage directly, bypassing ExpiringAgentNetworkStorage,
            # the way a pre-filtering server instance would have.
            await storage.add_reservations({reservation: ByokAgentSpecBuilder.make_spec(reservation_id)},
                                           source="unit-test")

            # Guard against a vacuous pass: the on-disk spec really is unresolved.
            path: str = os.path.join(base_path, f"{reservation_id}.json")
            with open(path, "r", encoding="utf-8") as file_handle:
                on_disk: Dict[str, Any] = json.load(file_handle)
            self.assertNotIn("sly_data_schema", on_disk["tools"][0]["function"])

            got_reservation: Optional[Reservation]
            got_network: Optional[AgentNetwork]
            got_reservation, got_network = storage.get_one_reservation(reservation_id)

            # Reading resolves in memory only; the file is left exactly as written.
            with open(path, "r", encoding="utf-8") as file_handle:
                after_read: Dict[str, Any] = json.load(file_handle)
            self.assertEqual(on_disk, after_read)

            self.assertIsNotNone(got_reservation)
            self.assertIsInstance(got_network, AgentNetwork)
            front_man_spec: Dict[str, Any] = ByokAgentSpecBuilder.front_man_spec(got_network)
            self.assertEqual(["llm_config"], front_man_spec["function"]["sly_data_schema"]["required"])
            self.assertIn("fallbacks", front_man_spec["llm_config"])
