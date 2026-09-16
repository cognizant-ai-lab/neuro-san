
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
Pins the read-side safety net of the reservation READ path: an S3 object whose
agent spec never went through the NetworkConfigFilterChain must still come back
as a fully resolved AgentNetwork.

ExpiringAgentNetworkStorage resolves specs before writing them, so in steady
state the reader's filtering is a no-op (the chain is idempotent).  It matters
during rolling upgrades, when an older instance may still write raw specs that
a newer instance then reads, and for objects placed in the bucket by other tooling.
"""
import json
import time
from typing import Any
from typing import Dict
from typing import Optional

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util

from tests.neuro_san.internals.network_providers.byok_agent_spec_builder import ByokAgentSpecBuilder
from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestReaderFiltersRawSpec(S3ReservationsStorageTestBase):
    """
    Verifies that get_one_reservation() applies the NetworkConfigFilterChain to
    a raw spec read from S3, so the front man ends up advertising the deployment's
    global sly_data_schema just like a network served from memory would.
    """

    def _put_raw_byok_reservation(self, reservation_id: str) -> str:
        """
        Place an unexpired reservation object whose agent spec has NOT been through the
        filter chain directly into the fake bucket, matching the writer's on-disk schema
        but bypassing ExpiringAgentNetworkStorage (which would have resolved it).

        :param reservation_id: The reservation id, which readers turn into the S3 key
        :return: The reservation id
        """
        agent_spec: Dict[str, Any] = ByokAgentSpecBuilder.make_spec(reservation_id)
        agent_spec["metadata"] = {
            "reservation": {
                "id": reservation_id,
                "lifetime_in_seconds": 3600.0,
                "expiration_time_in_seconds": time.time() + 3600.0,
            },
            "stored_at": time.time(),
        }
        key: str = S3Util.get_obj_key_for_reservation(self.PREFIX, reservation_id)
        self.fake_s3.objects[key] = json.dumps(agent_spec).encode("utf-8")
        return reservation_id

    def test_read_resolves_raw_spec(self):
        """
        Reading a raw spec yields an AgentNetwork whose front man carries the merged
        global sly_data_schema and the network-level llm_config.
        """
        reservation_id: str = self._put_raw_byok_reservation("byok-raw")

        reservation: Optional[Reservation]
        agent_network: Optional[AgentNetwork]
        reservation, agent_network = self.storage.get_one_reservation(reservation_id)

        self.assertIsNotNone(reservation)
        self.assertIsInstance(agent_network, AgentNetwork)
        front_man_spec: Dict[str, Any] = ByokAgentSpecBuilder.front_man_spec(agent_network)
        self.assertEqual(["llm_config"], front_man_spec["function"]["sly_data_schema"]["required"])
        self.assertIn("openai_api_key",
                      front_man_spec["function"]["sly_data_schema"]["properties"]["llm_config"]["properties"])
        self.assertIn("fallbacks", front_man_spec["llm_config"])
