
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
Round-trip a single reservation through S3ReservationsStorage.
"""
from tests.neuro_san.service.watcher.temp_networks.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestRoundTrip(S3ReservationsStorageTestBase):
    """
    Reservation feature works end-to-end against an S3-like backend:
    writing a reservation and reading it back yields an equivalent
    Reservation and an AgentNetwork carrying the original agent spec.
    """

    def test_add_then_get_returns_equivalent_reservation(self):
        """
        Uses a reservation id and an authored network name that are
        deliberately different strings so each assertion below exercises
        a distinct code path (storage-assigned registry name vs
        JSON-persisted spec name).
        """
        # Reservation id mimics the production "<prefix>-<uuid4>" shape
        # (see AgentReservation.get_reservation_id), but uses a stable,
        # easily grep-able placeholder in place of a real UUID so the
        # test is deterministic. Format breakdown:
        #   "copy_cat"   <- prefix; the agent network name being reserved
        #   "-"          <- separator inserted by AgentReservation
        #   "test-UUID-0001"
        #                <- where a real uuid4() string would normally
        #                   appear; "test-UUID" is an obvious test marker
        #                   so any leaked value is identifiable as a
        #                   fixture, and "0001" lets multi-reservation
        #                   tests append "0002", "0003", etc.
        reservation_id = "copy_cat-test-UUID-0001"
        # Bare network name as it would appear in a HOCON registry entry,
        # distinct from the reservation id.
        agent_spec_name = "copy_cat"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=1234.5)
        agent_spec = self._make_agent_spec(agent_spec_name)

        # Write
        self.storage.add_reservations({reservation: agent_spec})

        # Read. Capture the lookup id in its own variable so the assertion
        # messages below always reflect the exact value passed to
        # get_one_reservation, even if a future maintainer mutates the call
        # for a sanity check.
        lookup_id = reservation_id
        returned_reservation, returned_network = \
            self.storage.get_one_reservation(lookup_id)

        # Reservation came back with all the fields intact.
        self.assertIsNotNone(
            returned_reservation,
            f"get_one_reservation({lookup_id!r}) returned None for the "
            "reservation that was just written via add_reservations(); the "
            "write/read round-trip is broken.",
        )
        self.assertEqual(
            reservation.get_reservation_id(),
            returned_reservation.get_reservation_id(),
            "Reservation id changed after S3 round-trip.",
        )
        self.assertEqual(
            reservation.get_lifetime_in_seconds(),
            returned_reservation.get_lifetime_in_seconds(),
            "Reservation lifetime_in_seconds changed after S3 round-trip.",
        )
        self.assertEqual(
            reservation.get_expiration_time_in_seconds(),
            returned_reservation.get_expiration_time_in_seconds(),
            "Reservation expiration_time_in_seconds changed after S3 round-trip.",
        )

        # Agent network came back and carries the original spec under the
        # reservation id used as its name.
        self.assertIsNotNone(
            returned_network,
            f"get_one_reservation({lookup_id!r}) returned a None "
            "AgentNetwork; the agent spec stored alongside the reservation "
            "could not be reconstructed from S3.",
        )
        self.assertEqual(
            reservation_id,
            returned_network.name,
            "Returned AgentNetwork.name does not match the reservation id used "
            "as its registry name.",
        )
        self.assertEqual(
            agent_spec_name,
            returned_network.get_config().get("name"),
            "Original agent_spec['name'] was not preserved through S3 round-trip.",
        )
        self.assertEqual(
            agent_spec.get("tools"),
            returned_network.get_config().get("tools"),
            "Original agent_spec['tools'] was not preserved through S3 round-trip.",
        )
        self.assertEqual(
            agent_spec.get("llm_config"),
            returned_network.get_config().get("llm_config"),
            "Original agent_spec['llm_config'] was not preserved through "
            "S3 round-trip.",
        )
