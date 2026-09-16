
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
import time
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util

from tests.neuro_san.internals.network_providers.byok_agent_spec_builder import ByokAgentSpecBuilder
from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestS3ReservationsReader(S3ReservationsStorageTestBase):
    """
    Unit tests for S3ReservationsReader, reached through the reader that
    S3ReservationsStorageTestBase wires to an in-memory fake S3 client.

    The read path resolves each stored agent spec through NetworkConfigFilterChain
    before building the AgentNetwork.  ExpiringAgentNetworkStorage already resolves
    specs before writing them, so in steady state that is a no-op; it matters for
    objects written by older instances during a rolling upgrade or by other tooling.
    Such objects never went through the reservationist's validators, so the reader
    must also treat a spec that makes the chain raise as "not present" rather than
    let the exception escape onto the request path, matching LocalReservationsStorage.
    """

    def _put_raw_byok_reservation(self, reservation_id: str, overrides: Dict[str, Any] = None) -> str:
        """
        Place an unexpired reservation object whose agent spec has NOT been through the
        filter chain directly into the fake bucket, matching the writer's on-disk schema
        but bypassing ExpiringAgentNetworkStorage (which would have resolved it).

        :param reservation_id: The reservation id, which readers turn into the S3 key
        :param overrides: Optional top-level keys to set on the spec before it is stored,
                used to make the spec malformed on purpose. None means store it as built.
        :return: The reservation id
        """
        agent_spec: Dict[str, Any] = ByokAgentSpecBuilder.make_spec(reservation_id)
        if overrides is not None:
            agent_spec.update(overrides)
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

    def test_get_one_reservation_resolves_raw_spec(self):
        """
        Reading a raw spec yields an AgentNetwork whose front man carries the merged
        global sly_data_schema and the network-level llm_config.
        """
        reservation_id: str = self._put_raw_byok_reservation("byok-raw")

        reservation: Optional[Reservation]
        agent_network: Optional[AgentNetwork]
        reservation, agent_network = self.storage.reader.get_one_reservation(reservation_id)

        self.assertIsNotNone(reservation)
        self.assertIsInstance(agent_network, AgentNetwork)
        front_man_spec: Dict[str, Any] = ByokAgentSpecBuilder.front_man_spec(agent_network)
        self.assertEqual(["llm_config"], front_man_spec["function"]["sly_data_schema"]["required"])
        self.assertIn("openai_api_key",
                      front_man_spec["function"]["sly_data_schema"]["properties"]["llm_config"]["properties"])
        self.assertIn("fallbacks", front_man_spec["llm_config"])

    def test_get_one_reservation_reports_chain_error_as_absent(self):
        """
        A commondefs block that is not a dictionary makes the commondefs filter raise;
        the reader must swallow that and report the reservation as absent.
        """
        reservation_id: str = self._put_raw_byok_reservation("byok-bad-commondefs", {"commondefs": "oops"})

        result: Tuple[Optional[Reservation], Optional[AgentNetwork]] = \
            self.storage.reader.get_one_reservation(reservation_id)

        self.assertEqual((None, None), result)

    def test_get_one_reservation_reports_defaults_merge_error_as_absent(self):
        """
        A global sly_data_schema whose "required" is a string instead of a list makes
        DefaultsConfigFilter's union raise; the same policy applies.
        """
        bad_schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": "llm_config"}
        reservation_id: str = self._put_raw_byok_reservation("byok-bad-required", {"sly_data_schema": bad_schema})
        # The front man must declare its own list-valued "required" for the union to be attempted.
        spec_key: str = S3Util.get_obj_key_for_reservation(self.PREFIX, reservation_id)
        stored: Dict[str, Any] = json.loads(self.fake_s3.objects[spec_key])
        stored["tools"][0]["function"]["sly_data_schema"] = {"type": "object", "required": ["http_headers"]}
        self.fake_s3.objects[spec_key] = json.dumps(stored).encode("utf-8")

        result: Tuple[Optional[Reservation], Optional[AgentNetwork]] = \
            self.storage.reader.get_one_reservation(reservation_id)

        self.assertEqual((None, None), result)
