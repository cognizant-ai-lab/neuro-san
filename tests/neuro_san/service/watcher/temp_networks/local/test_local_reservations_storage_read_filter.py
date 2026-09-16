
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
import json
import os
import tempfile
from typing import Any
from typing import Dict
from unittest import IsolatedAsyncioTestCase

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.service.watcher.temp_networks.local.local_reservations_storage import LocalReservationsStorage

from tests.neuro_san.internals.network_providers.byok_agent_spec_builder import ByokAgentSpecBuilder
from tests.neuro_san.service.watcher.temp_networks.local.local_reservations_test_helpers \
    import LocalReservationsTestHelpers


class TestLocalReservationsStorageReadFilter(IsolatedAsyncioTestCase):
    """
    Read-path tests for how LocalReservationsStorage handles unresolved agent specs.

    ExpiringAgentNetworkStorage resolves specs through the NetworkConfigFilterChain before
    writing them, but a file written directly (by an older server instance during a rolling
    upgrade, or by other tooling) may still hold a raw spec.  get_one_reservation() must
    resolve such a spec so the AgentNetwork it returns carries the same top-level defaults
    as one served from memory.
    """

    async def test_read_resolves_raw_spec(self):
        """
        A raw spec written straight to disk comes back with the global sly_data_schema
        merged into the front man, while the file itself is left exactly as written.
        """
        with tempfile.TemporaryDirectory() as base_path:
            storage = LocalReservationsStorage(base_path=base_path)
            storage.start()
            reservation = LocalReservationsTestHelpers.make_reservation(prefix="raw", lifetime_s=3600.0)
            reservation_id: str = reservation.get_reservation_id()
            # Write through the storage directly, bypassing ExpiringAgentNetworkStorage,
            # the way a pre-filtering server instance would have.
            await storage.add_reservations({reservation: ByokAgentSpecBuilder.make_spec(reservation_id)},
                                           source="unit-test")

            # Guard against a vacuous pass: the on-disk spec really is unresolved.
            with open(os.path.join(base_path, f"{reservation_id}.json"), "r", encoding="utf-8") as file_handle:
                on_disk: Dict[str, Any] = json.load(file_handle)
            self.assertNotIn("sly_data_schema", on_disk["tools"][0]["function"])

            got_reservation, got_network = storage.get_one_reservation(reservation_id)

            self.assertIsNotNone(got_reservation)
            self.assertIsInstance(got_network, AgentNetwork)
            front_man_spec: Dict[str, Any] = ByokAgentSpecBuilder.front_man_spec(got_network)
            self.assertEqual(["llm_config"], front_man_spec["function"]["sly_data_schema"]["required"])
            self.assertIn("fallbacks", front_man_spec["llm_config"])
