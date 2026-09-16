
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
from typing import Any
from typing import Dict

from copy import deepcopy
import time
from unittest import IsolatedAsyncioTestCase

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.filters.network_config_filter_chain import NetworkConfigFilterChain
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.network_providers.expiring_agent_network_storage \
    import ExpiringAgentNetworkStorage

from tests.neuro_san.internals.network_providers.byok_agent_spec_builder \
    import ByokAgentSpecBuilder
from tests.neuro_san.internals.network_providers.recording_listener \
    import RecordingListener
from tests.neuro_san.internals.network_providers.recording_reservations_storage \
    import RecordingReservationsStorage


# pylint: disable=too-many-public-methods
class TestExpiringAgentNetworkStorage(IsolatedAsyncioTestCase):
    """
    Unit tests for ExpiringAgentNetworkStorage LRU eviction and access tracking functionality.
    """

    @staticmethod
    def _make_reservation(name: str, lifetime: float = 3600.0) -> Reservation:
        """
        Create a Reservation with a given name and expiration far in the future.
        """
        reservation = Reservation(lifetime_in_seconds=lifetime)
        reservation.id = name
        reservation.expiration_time_in_seconds = time.time() + lifetime
        return reservation

    @staticmethod
    def _make_expired_reservation(name: str) -> Reservation:
        """
        Create a Reservation that is already expired.
        """
        reservation = Reservation(lifetime_in_seconds=0.0)
        reservation.id = name
        reservation.expiration_time_in_seconds = 0.0
        return reservation

    @staticmethod
    def _make_agent_spec(name: str) -> dict:
        """
        Create a minimal agent network spec dictionary.
        """
        return {"name": name, "tools": []}

    @staticmethod
    def _make_storage(max_items: int = 0) -> ExpiringAgentNetworkStorage:
        """
        Create storage with expiration checking disabled (interval=0).
        """
        storage = ExpiringAgentNetworkStorage(check_expirations_interval_seconds=0)
        if max_items > 0:
            storage.set_max_agent_networks(max_items)
        return storage

    def test_construction(self):
        """
        Test that storage can be constructed with default parameters.
        """
        storage = self._make_storage()
        self.assertIsNotNone(storage)
        self.assertEqual(0, storage.max_items)
        self.assertEqual(0, len(storage.agents_table))

    async def test_add_reservations(self):
        """
        Test that reservations can be added and are tracked in all tables.
        """
        storage = self._make_storage()
        r_a = self._make_reservation("agent_a")
        await storage.add_reservations({r_a: self._make_agent_spec("agent_a")}, source="test")
        self.assertIn("agent_a", storage.agents_table)
        self.assertIn("agent_a", storage.reservations_table)
        self.assertIn("agent_a", storage.access_times)

    async def test_add_reservations_replaces_existing(self):
        """
        Test that adding a reservation with the same name replaces it.
        """
        storage = self._make_storage()
        listener = RecordingListener()
        storage.add_listener(listener)

        r_a = self._make_reservation("agent_a")
        await storage.add_reservations({r_a: self._make_agent_spec("agent_a")}, source="test")
        self.assertEqual(["agent_a"], listener.added)

        # Add again with same name
        listener.reset()
        r_a2 = self._make_reservation("agent_a")
        await storage.add_reservations({r_a2: self._make_agent_spec("agent_a")}, source="test")
        self.assertEqual([], listener.added)
        self.assertEqual(["agent_a"], listener.modified)
        self.assertEqual(1, len(storage.agents_table))

    def test_set_max_agent_networks(self):
        """
        Test that set_max_agent_networks correctly sets max_items and overflow threshold.
        """
        storage = self._make_storage()
        storage.set_max_agent_networks(100)
        self.assertEqual(100, storage.max_items)
        # 5% of 100 = 5
        self.assertEqual(5, storage.items_overflow_threshold)

    def test_set_max_agent_networks_small(self):
        """
        Test that overflow threshold minimum is 1 for small max_items values.
        """
        storage = self._make_storage()
        storage.set_max_agent_networks(5)
        self.assertEqual(5, storage.max_items)
        self.assertEqual(1, storage.items_overflow_threshold)

    def test_set_max_agent_networks_unlimited(self):
        """
        Test that setting max_items to 0 means unlimited.
        """
        storage = self._make_storage()
        storage.set_max_agent_networks(0)
        self.assertEqual(0, storage.max_items)
        self.assertEqual(0, storage.items_overflow_threshold)

    async def test_no_eviction_when_unlimited(self):
        """
        Test that no eviction occurs when max_items is 0 (unlimited).
        """
        storage = self._make_storage()
        for i in range(20):
            r = self._make_reservation(f"agent_{i}")
            await storage.add_reservations({r: self._make_agent_spec(f"agent_{i}")}, source="test")
        self.assertEqual(20, len(storage.agents_table))

    async def test_lru_eviction_on_add(self):
        """
        Test that LRU eviction occurs when adding items beyond the limit.
        """
        # max_items=5 means threshold=1, so eviction triggers when count > 5 + 1 = 6
        storage = self._make_storage(max_items=5)
        listener = RecordingListener()
        storage.add_listener(listener)

        # Add items with staggered access times
        for i in range(5):
            r = self._make_reservation(f"agent_{i}")
            await storage.add_reservations({r: self._make_agent_spec(f"agent_{i}")}, source="test")
            time.sleep(0.005)

        self.assertEqual(5, len(storage.agents_table))
        listener.reset()

        # Add 2 more to exceed the overflow threshold (5 + 1 = 6)
        for i in range(5, 7):
            r = self._make_reservation(f"agent_{i}")
            await storage.add_reservations({r: self._make_agent_spec(f"agent_{i}")}, source="test")
            time.sleep(0.005)

        # Eviction should have brought us back to max_items or below
        self.assertLessEqual(len(storage.agents_table), 5)
        # Oldest agents should have been evicted
        self.assertTrue(len(listener.removed) > 0)

    async def test_lru_eviction_preserves_recently_accessed(self):
        """
        Test that recently accessed items survive LRU eviction.
        """
        # Use a larger max_items to get a bigger threshold window for predictable behavior
        storage = self._make_storage(max_items=20)
        listener = RecordingListener()
        storage.add_listener(listener)

        # Add 20 items
        for i in range(20):
            r = self._make_reservation(f"agent_{i}")
            await storage.add_reservations({r: self._make_agent_spec(f"agent_{i}")}, source="test")
            time.sleep(0.002)

        # Access agent_0 to make it recently used
        provider = storage.get_agent_network_provider("agent_0")
        self.assertIsNotNone(provider)

        listener.reset()

        # Add enough more to trigger eviction (threshold is max(1, round(20*0.05))=1, so need 22 total)
        for i in range(20, 22):
            r = self._make_reservation(f"agent_{i}")
            await storage.add_reservations({r: self._make_agent_spec(f"agent_{i}")}, source="test")

        # agent_0 should still be present (it was recently accessed)
        self.assertIn("agent_0", storage.agents_table)
        # Some older agents should have been evicted
        self.assertTrue(len(listener.removed) > 0)

    async def test_access_time_updated_on_get(self):
        """
        Test that accessing an agent network updates its access time.
        """
        storage = self._make_storage()
        r_a = self._make_reservation("agent_a")
        await storage.add_reservations({r_a: self._make_agent_spec("agent_a")}, source="test")

        original_time = storage.access_times["agent_a"]
        time.sleep(0.01)

        provider = storage.get_agent_network_provider("agent_a")
        self.assertIsNotNone(provider)
        self.assertGreater(storage.access_times["agent_a"], original_time)

    async def test_access_time_set_on_add(self):
        """
        Test that access time is set when a reservation is added.
        """
        storage = self._make_storage()
        before = time.time()
        r_a = self._make_reservation("agent_a")
        await storage.add_reservations({r_a: self._make_agent_spec("agent_a")}, source="test")
        after = time.time()

        self.assertIn("agent_a", storage.access_times)
        self.assertGreaterEqual(storage.access_times["agent_a"], before)
        self.assertLessEqual(storage.access_times["agent_a"], after)

    async def test_expire_removes_access_times(self):
        """
        Test that expiring a reservation also removes its access time entry.
        """
        storage = self._make_storage()
        r_expired = self._make_expired_reservation("agent_expired")
        await storage.add_reservations({r_expired: self._make_agent_spec("agent_expired")}, source="test")

        self.assertIn("agent_expired", storage.access_times)

        storage.expire_reservations()

        self.assertNotIn("agent_expired", storage.agents_table)
        self.assertNotIn("agent_expired", storage.reservations_table)
        self.assertNotIn("agent_expired", storage.access_times)

    async def test_get_expired_removes_access_times(self):
        """
        Test that getting an expired agent removes its access time entry.
        """
        storage = self._make_storage()
        r_expired = self._make_expired_reservation("agent_expired")
        await storage.add_reservations({r_expired: self._make_agent_spec("agent_expired")}, source="test")

        provider = storage.get_agent_network_provider("agent_expired")
        self.assertIsNone(provider)
        self.assertNotIn("agent_expired", storage.access_times)

    async def test_remove_agent_network_cleans_all_tables(self):
        """
        Test that remove_agent_network removes from all three tables.
        """
        storage = self._make_storage()
        r_a = self._make_reservation("agent_a")
        await storage.add_reservations({r_a: self._make_agent_spec("agent_a")}, source="test")

        storage.remove_agent_network("agent_a")

        self.assertNotIn("agent_a", storage.agents_table)
        self.assertNotIn("agent_a", storage.reservations_table)
        self.assertNotIn("agent_a", storage.access_times)

    def test_remove_nonexistent_agent_is_safe(self):
        """
        Test that removing a nonexistent agent does not raise an error.
        """
        storage = self._make_storage()
        storage.remove_agent_network("does_not_exist")

    async def test_eviction_notifies_listeners(self):
        """
        Test that listeners are notified when agents are evicted.
        """
        storage = self._make_storage(max_items=5)
        listener = RecordingListener()
        storage.add_listener(listener)

        # Fill storage and trigger eviction
        for i in range(8):
            r = self._make_reservation(f"agent_{i}")
            await storage.add_reservations({r: self._make_agent_spec(f"agent_{i}")}, source="test")
            time.sleep(0.005)

        # Some agents should have been removed via eviction
        self.assertTrue(len(listener.removed) > 0)

    async def test_set_max_evicts_existing(self):
        """
        Test that calling set_max_agent_networks on a storage
        that already has items triggers eviction if needed.
        """
        storage = self._make_storage()
        listener = RecordingListener()
        storage.add_listener(listener)

        # Add 10 items with no limit
        for i in range(10):
            r = self._make_reservation(f"agent_{i}")
            await storage.add_reservations({r: self._make_agent_spec(f"agent_{i}")}, source="test")
            time.sleep(0.005)

        self.assertEqual(10, len(storage.agents_table))
        listener.reset()

        # Now set a limit of 3
        storage.set_max_agent_networks(3)

        # Eviction should have reduced to 3
        self.assertLessEqual(len(storage.agents_table), 3)
        self.assertTrue(len(listener.removed) > 0)

    async def test_add_empty_reservations(self):
        """
        Test that adding an empty dict is a no-op.
        """
        storage = self._make_storage(max_items=5)
        await storage.add_reservations({}, source="test")
        self.assertEqual(0, len(storage.agents_table))

    def test_get_nonexistent_returns_none(self):
        """
        Test that getting a nonexistent agent returns None.
        """
        storage = self._make_storage()
        provider = storage.get_agent_network_provider("does_not_exist")
        self.assertIsNone(provider)

    async def test_get_valid_returns_provider(self):
        """
        Test that getting a valid agent returns a non-None provider.
        """
        storage = self._make_storage()
        r_a = self._make_reservation("agent_a")
        await storage.add_reservations({r_a: self._make_agent_spec("agent_a")}, source="test")

        provider = storage.get_agent_network_provider("agent_a")
        self.assertIsNotNone(provider)

    async def test_expire_mixed(self):
        """
        Test that only expired reservations are removed, valid ones remain.
        """
        storage = self._make_storage()
        r_valid = self._make_reservation("valid")
        r_expired = self._make_expired_reservation("expired")

        await storage.add_reservations({
            r_valid: self._make_agent_spec("valid"),
            r_expired: self._make_agent_spec("expired"),
        }, source="test")

        storage.expire_reservations()

        self.assertIn("valid", storage.agents_table)
        self.assertIn("valid", storage.access_times)
        self.assertNotIn("expired", storage.agents_table)
        self.assertNotIn("expired", storage.access_times)

    async def test_tables_stay_consistent(self):
        """
        Test that agents_table, reservations_table, and access_times
        remain consistent through adds, accesses, and evictions.
        """
        storage = self._make_storage(max_items=5)

        for i in range(8):
            r = self._make_reservation(f"agent_{i}")
            await storage.add_reservations({r: self._make_agent_spec(f"agent_{i}")}, source="test")
            time.sleep(0.005)

        # All three tables should have the same keys
        self.assertEqual(
            set(storage.agents_table.keys()),
            set(storage.reservations_table.keys())
        )
        self.assertEqual(
            set(storage.agents_table.keys()),
            set(storage.access_times.keys())
        )

    async def test_add_reservations_merges_global_sly_data_schema_into_front_man(self):
        """
        A reservation spec never passes through AgentNetworkRestorer, so add_reservations
        must run the NetworkConfigFilterChain itself.  The visible effect is that the
        deployment-wide sly_data_schema ends up on the front man's function, which is
        what the /function endpoint serves to clients deciding whether to send BYOK keys.
        """
        storage: ExpiringAgentNetworkStorage = self._make_storage()
        r_a: Reservation = self._make_reservation("agent_a")
        await storage.add_reservations({r_a: ByokAgentSpecBuilder.make_spec("agent_a")}, source="test")

        agent_network: AgentNetwork = storage.agents_table["agent_a"]
        front_man_spec: Dict[str, Any] = ByokAgentSpecBuilder.front_man_spec(agent_network)
        sly_data_schema: Dict[str, Any] = front_man_spec["function"]["sly_data_schema"]
        self.assertEqual(["llm_config"], sly_data_schema["required"])
        self.assertIn("openai_api_key", sly_data_schema["properties"]["llm_config"]["properties"])

        # The other top-level defaults are applied as well: llm_config lands on every agent...
        self.assertIn("fallbacks", front_man_spec["llm_config"])
        helper_spec: Dict[str, Any] = agent_network.get_agent_tool_spec("helper")
        self.assertIn("fallbacks", helper_spec["llm_config"])
        # ... and so does every other top-level default the runtime reads per agent.
        self.assertEqual(600, front_man_spec["max_execution_seconds"])
        self.assertEqual(600, helper_spec["max_execution_seconds"])
        # ... but only the front man advertises the sly_data_schema.
        self.assertNotIn("sly_data_schema", helper_spec["function"])

    async def test_add_reservations_unions_front_man_sly_data_schema_with_global(self):
        """
        When the front man already declares a sly_data_schema of its own (e.g. http_headers
        for MCP servers), the global one is merged into it and the "required" lists are
        unioned rather than one replacing the other.
        """
        front_man_schema: Dict[str, Any] = {
            "type": "object",
            "properties": {"http_headers": {"type": "object"}},
            "required": ["http_headers"],
        }
        storage: ExpiringAgentNetworkStorage = self._make_storage()
        r_a: Reservation = self._make_reservation("agent_a")
        await storage.add_reservations(
            {r_a: ByokAgentSpecBuilder.make_spec("agent_a", front_man_schema=front_man_schema)},
            source="test")

        front_man_spec: Dict[str, Any] = ByokAgentSpecBuilder.front_man_spec(storage.agents_table["agent_a"])
        sly_data_schema: Dict[str, Any] = front_man_spec["function"]["sly_data_schema"]
        self.assertCountEqual(["llm_config", "http_headers"], sly_data_schema["required"])
        self.assertIn("http_headers", sly_data_schema["properties"])
        self.assertIn("llm_config", sly_data_schema["properties"])

    async def test_add_reservations_writes_resolved_spec_to_base_storage(self):
        """
        The base storage is the source of truth for other server instances, so the spec it
        receives must already be resolved; filtering only the in-memory copy would leave
        every other instance serving the raw spec.  The in-memory AgentNetwork must also be
        built from the very dictionary handed to the base storage, so metadata a writer adds
        to it (e.g. the S3 writer's reservation block) stays consistent with what is served here.
        """
        storage: ExpiringAgentNetworkStorage = self._make_storage()
        base_storage: RecordingReservationsStorage = RecordingReservationsStorage()
        storage.set_base_storage(base_storage)
        r_a: Reservation = self._make_reservation("agent_a")
        await storage.add_reservations({r_a: ByokAgentSpecBuilder.make_spec("agent_a")}, source="test")

        self.assertEqual(1, len(base_storage.received))
        self.assertEqual(["test"], base_storage.sources)
        written: Dict[Reservation, Dict[str, Any]] = base_storage.received[0]
        self.assertEqual([r_a], list(written.keys()))
        written_spec: Dict[str, Any] = written[r_a]
        self.assertEqual(["llm_config"], written_spec["tools"][0]["function"]["sly_data_schema"]["required"])
        self.assertIs(written_spec, storage.agents_table["agent_a"].get_config())

    async def test_add_reservations_does_not_mutate_caller_spec(self):
        """
        Filtering must not leak into the caller's dictionary: reservationists and coded tools
        may keep using the spec they deployed, and DefaultsConfigFilter works on a copy.
        """
        storage: ExpiringAgentNetworkStorage = self._make_storage()
        spec: Dict[str, Any] = ByokAgentSpecBuilder.make_spec("agent_a")
        expected: Dict[str, Any] = deepcopy(spec)
        r_a: Reservation = self._make_reservation("agent_a")
        await storage.add_reservations({r_a: spec}, source="test")

        # The whole dictionary, not just the keys the filter is known to touch.
        self.assertEqual(expected, spec)

    def test_filter_reservations_is_idempotent(self):
        """
        Specs that are already resolved (e.g. read back from base storage) must come out
        unchanged, so filtering on both the write side and the read side is safe.

        The commondefs filters resolve one level of substitution per pass and never remove the
        "commondefs" block, so a spec that kept it would keep changing on every pass.
        filter_reservations() therefore strips the block, and its result must equal what a
        single hocon-style pass of the chain produces (minus that block).
        """
        spec: Dict[str, Any] = ByokAgentSpecBuilder.make_spec("agent_a")
        spec["commondefs"] = {
            # Chained value substitution: a single pass resolves only one hop.
            "replacement_values": {"a": "b", "b": {"z": 1}},
            # Order-dependent string substitution: "punct" is visited before "who" needs it.
            "replacement_strings": {"punct": "!", "who": "world {punct}", "greet": "hello {who}"},
        }
        spec["tools"][0]["args"] = {"x": "a"}
        spec["tools"][0]["instructions"] = "{greet}"
        expected: Dict[str, Any] = NetworkConfigFilterChain().filter_config(spec)
        del expected["commondefs"]

        r_a: Reservation = self._make_reservation("agent_a")
        once: Dict[Reservation, Dict[str, Any]] = ExpiringAgentNetworkStorage.filter_reservations({r_a: spec})
        snapshot: Dict[str, Any] = deepcopy(once[r_a])
        twice: Dict[Reservation, Dict[str, Any]] = ExpiringAgentNetworkStorage.filter_reservations(once)

        self.assertEqual([r_a], list(twice.keys()))
        self.assertNotIn("commondefs", once[r_a])
        self.assertEqual(expected, once[r_a])
        self.assertEqual(snapshot, twice[r_a])
        # The second pass did not mutate its input either.
        self.assertEqual(snapshot, once[r_a])
