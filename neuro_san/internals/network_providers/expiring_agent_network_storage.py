
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
from typing import List
from typing import Optional
from typing import Tuple

from logging import getLogger
from logging import Logger
import time

from leaf_common.config.config_filter import ConfigFilter
from leaf_common.logging.sensitive_logger import SensitiveLogger
from leaf_common.utils.map import Map
from leaf_common.utils.startable import Startable

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.filters.resolved_network_config_filter import ResolvedNetworkConfigFilter
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_storage_manager import AgentNetworkStorageManager
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.interfaces.agent_state_listener import AgentStateListener
from neuro_san.internals.interfaces.agent_storage_source import AgentStorageSource
from neuro_san.internals.interfaces.listenable import Listenable
from neuro_san.internals.interfaces.reservations_storage import ReservationsStorage
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.network_providers.abstract_reservations_storage \
    import AbstractReservationsStorage
from neuro_san.internals.network_providers.fixed_agent_network_provider import FixedAgentNetworkProvider


# pylint: disable=too-many-instance-attributes
class ExpiringAgentNetworkStorage(AbstractReservationsStorage, AgentNetworkStorageManager, AgentStorageSource,
                                  Listenable[AgentStateListener]):
    """
    An AgentNetworkStorage instance where AgentNetworks are allowed to expire.
    This implementation also allows for an optional "source" storage to be set,
    which will be used as a "base" source of truth.
    """

    def __init__(self, check_expirations_interval_seconds: float = 60.0):
        """
        Constructor
        :param check_expirations_interval_seconds: The number of seconds between checks for expired reservations.
        """
        super().__init__(storage_name="temp_storage",
                         check_expirations_interval_seconds=check_expirations_interval_seconds)

        self.network_storage: AgentNetworkStorage = AgentNetworkStorage()
        self.reservations_table: Dict[str, Reservation] = {}
        # Table maps agent name to the latest time it was accessed:
        self.access_times: Dict[str, float] = {}
        self.sizes: Dict[str, int] = {}

        # Maximum number of items to keep in storage. 0 or negative means unlimited.
        self.max_items: int = 0
        # Threshold for items eviction when number of items in storage exceeds
        # specified maximum by that number.
        self.items_overflow_threshold: int = 0

        self.base_storage: ReservationsStorage = None
        self.logger: Logger = getLogger(self.__class__.__name__)

    def set_base_storage(self, base_storage: ReservationsStorage):
        """
        Set the base storage to be used as a "source of truth" for reservations and agent networks.
        This is optional, but if set, then this storage will be used as a source of truth
        for reservations and agent networks,
        and any changes to reservations and agent networks in this storage will be reflected in this storage as well.

        :param base_storage: An ExpiringReservationsStorage instance to be used
                             as a source of truth for reservations and agent networks.
        """
        self.base_storage = base_storage

    def set_max_agent_networks(self, max_items: int):
        """
        Configure the maximum number of temporary networks to keep in memory.
        When exceeded, least recently used items are evicted.

        :param max_items: Maximum number of items. 0 or negative means unlimited.
        """
        self.max_items = max_items
        self.items_overflow_threshold = 0
        # Compute some reasonable overflow threshold to avoid evicting items one by one
        # when we are just slightly above the limit.
        if max_items > 0:
            # Set overflow threshold to 5% of max_items, rounded up, with a minimum of 1:
            self.items_overflow_threshold = max(1, round(max_items * 0.05))
        # Evict least recently used items if we exceeded the new limit
        self.evict_lru_agent_networks()

    def start(self):
        """
        Start this storage, which includes starting the expiration checking loop.
        """
        super().start()
        try:
            if self.base_storage is not None:
                self.base_storage.start()
        except Exception as exc:  # pylint: disable=broad-except
            sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)
            sensitive_logger.error("%s: Failed to start base storage: %s", self._name, exc)
            super().stop()
            raise

    def stop(self, timeout: Optional[float] = None):
        """
        Stop this storage, which includes stopping the expiration checking loop.
        """
        super().stop()
        try:
            if self.base_storage is not None and isinstance(self.base_storage, Startable):
                self.base_storage.stop()
        except Exception as exc:  # pylint: disable=broad-except
            sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)
            sensitive_logger.error("%s: Failed to stop base storage: %s", self._name, exc)
            raise

    @staticmethod
    def is_expired(reservation: Reservation) -> bool:
        """
        :return: Whether this reservation is expired or not.
        """
        return time.time() > reservation.get_expiration_time_in_seconds()

    # pylint: disable=too-many-locals
    async def add_reservations(self, reservations_dict: Map[Reservation, Dict[str, Any]],
                               source: str = None):
        """
        Add a set of reservations for agent networks en-masse

        :param reservations_dict: A mapping of Reservation -> agent network spec
        :param source: A string describing where the deployment was coming from
        """
        if not reservations_dict:
            # Nothing to do
            return

        # Resolve every spec *before* anything is stored.  See ResolvedNetworkConfigFilter for
        # why a reservation spec needs this at all (top-level defaults such as the BYOK
        # sly_data_schema never reach its agents otherwise).
        # Other instances hydrate temporary networks from the base storage (S3, local files, ...),
        # not from this instance's memory, so persisting the resolved spec is what makes their
        # read-side pass of the same filter a no-op and has every instance serve the same network.
        # The same resolved dictionaries are then used for the in-memory AgentNetworks below,
        # so any metadata a writer adds to them stays consistent with what is served here.
        # The filter always returns a copy, so the caller's dictionaries are neither stored
        # nor mutated, and a metadata-injecting writer (S3ReservationsWriter) cannot reach them.
        spec_filter: ConfigFilter = ResolvedNetworkConfigFilter()
        use_reservations: Map[Reservation, Dict[str, Any]] = {}
        reservation: Reservation = None
        agent_spec: Dict[str, Any] = None
        for reservation, agent_spec in reservations_dict.items():
            use_reservations[reservation] = spec_filter.filter_config(agent_spec)

        if self.base_storage is not None:
            # If we have a source storage, then we need to add these reservations there first:
            await self.base_storage.add_reservations(use_reservations, source=source)

        # Figure out what's new vs what's not.
        # Need to do this while holding the lock
        added: List[str] = []
        replaced: List[str] = []
        now: float = time.time()
        with self.network_storage as locked_storage:
            for reservation, agent_spec in use_reservations.items():

                use_reservation: Reservation = reservation
                agent_name: str = use_reservation.get_reservation_id()
                is_new: bool = locked_storage.get_without_lock(agent_name) is None

                agent_network: AgentNetwork = AgentNetwork(agent_spec, agent_name)
                locked_storage.put_without_lock(agent_name, agent_network)

                self.reservations_table[agent_name] = use_reservation
                self.access_times[agent_name] = now
                self.sizes[agent_name] = agent_network.get_size_in_bytes()

                if is_new:
                    added.append(agent_name)
                else:
                    replaced.append(agent_name)

        # Notify listeners about this state change:
        # do it outside of internal lock
        listener: AgentStateListener = None
        for listener in self.get_listeners():
            agent_name: str = None
            for agent_name in added:
                listener.agent_added(agent_name, self)
                agent_size_in_bytes: int = self.sizes.get(agent_name, 0)
                self.logger.info("%s: ADDED network for agent %s (%d bytes) from %s",
                                 self._name, agent_name, agent_size_in_bytes, source)
            for agent_name in replaced:
                listener.agent_modified(agent_name, self)
                agent_size_in_bytes: int = self.sizes.get(agent_name, 0)
                self.logger.info("%s: REPLACED network for agent %s (%d bytes) from %s",
                                 self._name, agent_name, agent_size_in_bytes, source)

        # Evict least recently used items if we exceeded the limit
        self.evict_lru_agent_networks()

    def get_one_reservation(self, obj_key: str) -> Tuple[Reservation, Any]:
        """
        Extract a single reservation.

        :param obj_key: unique key for the reservation
        :return: Tuple of (reservation, agent data) if successful
                 and reservation is not expired,
                 (None, None) otherwise
        """
        # For this class, this method is never used.
        raise NotImplementedError

    def expire_reservations(self):
        """
        Remove Reservations that are expired
        """

        # First determine what has expired
        expired: List[str] = []

        reservations_snapshot: Dict[str, Reservation] = self._get_reservations_snapshot()
        agent_name: str = None
        reservation: Reservation = None
        for agent_name, reservation in reservations_snapshot.items():
            if self.is_expired(reservation):
                expired.append(agent_name)

        # Nothing to do?
        if len(expired) == 0:
            return

        # Do the dirty deeds.
        with self.network_storage:
            for agent_name in expired:
                self.remove_agent_network(agent_name)

        # Notify listeners about this state change:
        # do it outside of internal lock
        listener: AgentStateListener = None
        for listener in self.get_listeners():
            for agent_name in expired:
                listener.agent_removed(agent_name, self)
                self.logger.info("%s: REMOVED network for agent %s", self._name, agent_name)

    def _get_reservations_snapshot(self) -> Dict[str, Reservation]:
        """
        Get a snapshot of all reservations
        """
        reservations_snapshot: Dict[str, Reservation] = None
        with self.network_storage:
            reservations_snapshot = self.reservations_table.copy()
        return reservations_snapshot

    def add_agent_network(self, agent_name: str, agent_network: AgentNetwork):
        """
        This method is a single point of entry in the service
        where we register a new agent name -> AgentNetwork pair.

        :param agent_name: name of an agent
        :param agent_network: An agent network
        """
        self.network_storage.add_agent_network(agent_name, agent_network)

    def remove_agent_network(self, agent_name: str):
        """
        Remove agent name and its AgentNetwork from service internal tables.
        :param agent_name: name of an agent to remove
        """
        self.reservations_table.pop(agent_name, None)
        self.access_times.pop(agent_name, None)
        self.sizes.pop(agent_name, None)
        self.network_storage.remove_agent_network(agent_name)

    def setup_agent_networks(self, agent_networks: Dict[str, AgentNetwork]):
        """
        Replace agents networks with a new collection.
        Previous state could be empty.

        :param agent_networks: A dictionary of agent name -> AgentNetwork
        """
        self.network_storage.setup_agent_networks(agent_networks)

    def get_agent_names(self) -> List[str]:
        """
        :return: The list of agent names being managed by the implementation.
        """
        return self.network_storage.get_agent_names()

    def evict_lru_agent_networks(self):
        """
        Remove least recently used agent networks to bring storage size under max_items limit.
        """
        if self.max_items <= 0:
            return

        evicted: List[str] = []
        with self.network_storage:
            agent_names: List[str] = self.network_storage.get_agent_names()
            overflow: int = len(agent_names) - self.max_items
            if overflow <= self.items_overflow_threshold:
                return
            # Sort by access time, oldest first
            sorted_agents: List[str] = sorted(self.access_times.items(), key=lambda item: item[1])
            agent_name: str = None
            for agent_name, _ in sorted_agents[:overflow]:
                self.remove_agent_network(agent_name)
                evicted.append(agent_name)

        # Notify listeners outside of lock
        listener: AgentStateListener = None
        for listener in self.get_listeners():
            agent_name: str = None
            for agent_name in evicted:
                listener.agent_removed(agent_name, self)
                self.logger.info("%s: EVICTED (LRU) network for agent %s", self._name, agent_name)

    def get_agent_network_provider(self, agent_name: str) -> AgentNetworkProvider:
        """
        Get AgentNetworkProvider for a specific agent
        :param agent_name: name of an agent
        """
        # Agents and their Reservations are always present or absent together.
        agent_network: AgentNetwork = None
        reservation: Reservation = self.reservations_table.get(agent_name, None)
        if reservation is not None:
            # We have a reservation for this agent, but we need to check is it still valid:
            if self.is_expired(reservation):
                # Reservation is expired, so AgentNetwork is gone for good:
                with self.network_storage:
                    self.remove_agent_network(agent_name)

                # Notify listeners about this state change:
                # do it outside of internal lock
                listener: AgentStateListener = None
                for listener in self.get_listeners():
                    listener.agent_removed(agent_name, self)
                    self.logger.info("%s: REMOVED expired network for agent %s", self._name, agent_name)

                # Now if we have a source storage,
                # we rely on it to expire this reservation according to its own schedule.

                # Our agent network no longer exists.
                return None

            # Reservation is still valid, so we can return the AgentNetworkProvider for this agent.
            # Specifically get this without the lock, as we are only reading.
            agent_network = self.network_storage.get_without_lock(agent_name)
            if agent_network is not None:
                with self.network_storage:
                    self.access_times[agent_name] = time.time()
                return FixedAgentNetworkProvider(agent_network)
            return None

        # We don't have a reservation for this agent,
        # so check the source storage if we have one:
        if self.base_storage is not None:
            reservation, agent_network = self.base_storage.get_one_reservation(agent_name)
            if reservation is not None and not self.is_expired(reservation):
                agent_size_in_bytes: int = agent_network.get_size_in_bytes()
                # We have a valid reservation for this agent in the source storage,
                # so return the AgentNetworkProvider for this agent.
                # Also cache this reservation and agent network locally:
                now: float = time.time()
                with self.network_storage as locked_storage:
                    self.reservations_table[agent_name] = reservation
                    locked_storage.put_without_lock(agent_name, agent_network)
                    self.access_times[agent_name] = now
                    self.sizes[agent_name] = agent_size_in_bytes

                # Notify listeners about this state change:
                # do it outside of internal lock
                listener: AgentStateListener = None
                for listener in self.get_listeners():
                    listener.agent_added(agent_name, self)
                    self.logger.info("ADDED network for agent %s (%d bytes) from %s",
                                     agent_name, agent_size_in_bytes, "base storage")

                # Evict least recently used items if we exceeded the limit
                self.evict_lru_agent_networks()

                return FixedAgentNetworkProvider(agent_network)
        return None

    def add_listener(self, listener: AgentStateListener):
        """
        Add a listener to be notified when status of underlying object changes.
        """
        self.network_storage.add_listener(listener)

    def remove_listener(self, listener: AgentStateListener):
        """
        Remove a listener from registered set.
        """
        self.network_storage.remove_listener(listener)

    def get_listeners(self) -> List[AgentStateListener]:
        """
        Return a list of listeners.
        """
        return self.network_storage.get_listeners()
