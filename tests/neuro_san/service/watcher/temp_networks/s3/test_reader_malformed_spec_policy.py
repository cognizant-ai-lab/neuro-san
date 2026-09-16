
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
Pins the S3 reader's policy for reservation objects whose agent spec breaks the
NetworkConfigFilterChain: they are reported as absent, never raised.

The reader resolves specs on read so that objects written by older instances or
other tooling still get their defaults. Those objects never went through the
reservationist's validators, so the chain may raise on a malformed shape. Letting
that propagate would surface as an unhandled error on the request path (via
ExpiringAgentNetworkStorage.get_agent_network_provider) instead of the not-found
handling, and would diverge from LocalReservationsStorage, which already treats
any reconstruction failure as "not present".
"""
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


class TestReaderMalformedSpecPolicy(S3ReservationsStorageTestBase):
    """
    Verifies that get_one_reservation() returns (None, None) when the stored agent
    spec makes the filter chain raise, instead of letting the exception escape.
    """

    def _put_reservation_with(self, reservation_id: str, overrides: Dict[str, Any]) -> str:
        """
        Place an unexpired reservation object into the fake bucket whose agent spec is
        a valid BYOK-shaped spec with the given top-level keys overridden.

        :param reservation_id: The reservation id, which readers turn into the S3 key
        :param overrides: Top-level keys to set on the spec before it is stored
        :return: The reservation id
        """
        agent_spec: Dict[str, Any] = ByokAgentSpecBuilder.make_spec(reservation_id)
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

    def test_chain_error_reports_reservation_as_absent(self):
        """
        A commondefs block that is not a dictionary makes the commondefs filter raise;
        the reader must swallow that and report the reservation as absent.
        """
        reservation_id: str = self._put_reservation_with("byok-bad-commondefs", {"commondefs": "oops"})

        result: Tuple[Optional[Reservation], Optional[AgentNetwork]] = \
            self.storage.get_one_reservation(reservation_id)

        self.assertEqual((None, None), result)

    def test_defaults_merge_error_reports_reservation_as_absent(self):
        """
        A global sly_data_schema whose "required" is a string instead of a list makes
        DefaultsConfigFilter's union raise; same policy applies.
        """
        bad_schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": "llm_config"}
        reservation_id: str = self._put_reservation_with("byok-bad-required", {"sly_data_schema": bad_schema})
        # The front man must declare its own list-valued "required" for the union to be attempted.
        spec_key: str = S3Util.get_obj_key_for_reservation(self.PREFIX, reservation_id)
        stored: Dict[str, Any] = json.loads(self.fake_s3.objects[spec_key])
        stored["tools"][0]["function"]["sly_data_schema"] = {"type": "object", "required": ["http_headers"]}
        self.fake_s3.objects[spec_key] = json.dumps(stored).encode("utf-8")

        result: Tuple[Optional[Reservation], Optional[AgentNetwork]] = \
            self.storage.get_one_reservation(reservation_id)

        self.assertEqual((None, None), result)
