
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

import logging
import time

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.interfaces.reservations_storage import ReservationsStorage
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.network_providers.abstract_reservations_storage \
    import AbstractReservationsStorage
from neuro_san.internals.network_providers.fixed_agent_network_provider import FixedAgentNetworkProvider
from neuro_san.internals.interfaces.startable import Startable


class ExpiringAgentNetworkStorage(AbstractReservationsStorage, AgentNetworkStorage):
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
        self.reservations_table: Dict[str, Reservation] = {}
        # Table maps agent name to the latest time it was accessed:
        self.access_times: Dict[str, float] = {}

        # Maximum number of items to keep in storage. 0 or negative means unlimited.
        self.max_items: int = 0
        # Threshold for items eviction when number of items in storage exceeds
        # specified maximum by that number.
        self.items_overflow_threshold: int = 0

        self.base_storage: ReservationsStorage = None
        self.logger = logging.getLogger(self.__class__.__name__)

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
            self.logger.error("%s: Failed to start base storage: %s", self._name, exc)
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
            self.logger.error("%s: Failed to stop base storage: %s", self._name, exc)
            raise

    @staticmethod
    def is_expired(reservation: Reservation) -> bool:
        """
        :return: Whether this reservation is expired or not.
        """
        return time.time() > reservation.get_expiration_time_in_seconds()

    def add_reservations(self, reservations_dict: Dict[Reservation, Dict[str, Any]],
                         source: str = None):
        """
        Add a set of reservations for agent networks en-masse

        :param reservations_dict: A mapping of Reservation -> agent network spec
        :param source: A string describing where the deployment was coming from
        """
        if not reservations_dict:
            # Nothing to do
            return

        if self.base_storage is not None:
            # If we have a source storage, then we need to add these reservations there first:
            self.base_storage.add_reservations(reservations_dict, source=source)

        # Figure out what's new vs what's not.
        # Need to do this while holding the lock
        added: List[str] = []
        replaced: List[str] = []
        now: float = time.time()
        with self.lock:
            for reservation, agent_spec in reservations_dict.items():

                agent_name: str = reservation.get_reservation_id()
                is_new = self.agents_table.get(agent_name) is None

                agent_network = AgentNetwork(agent_spec, agent_name)
                self.agents_table[agent_name] = agent_network
                self.reservations_table[agent_name] = reservation
                self.access_times[agent_name] = now

                if is_new:
                    added.append(agent_name)
                else:
                    replaced.append(agent_name)

        # Notify listeners about this state change:
        # do it outside of internal lock
        for listener in self.listeners:
            for agent_name in added:
                listener.agent_added(agent_name, self)
                self.logger.info("%s: ADDED network for agent %s from %s", self._name, agent_name, source)
            for agent_name in replaced:
                listener.agent_modified(agent_name, self)
                self.logger.info("%s: REPLACED network for agent %s from %s", self._name, agent_name, source)

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

        reservations_snapshot: Dict[str, Reservation] = None
        with self.lock:
            reservations_snapshot = self.reservations_table.copy()

        for agent_name, reservation in reservations_snapshot.items():
            if self.is_expired(reservation):
                expired.append(agent_name)

        # Nothing to do?
        if len(expired) == 0:
            return

        # Do the dirty deeds.
        with self.lock:
            for agent_name in expired:
                self.remove_agent_network(agent_name)

        # Notify listeners about this state change:
        # do it outside of internal lock
        for listener in self.listeners:
            for agent_name in expired:
                listener.agent_removed(agent_name, self)
                self.logger.info("%s: REMOVED network for agent %s", self._name, agent_name)

    def remove_agent_network(self, agent_name: str):
        """
        Remove agent name and its AgentNetwork from service internal tables.
        :param agent_name: name of an agent to remove
        """
        self.reservations_table.pop(agent_name, None)
        self.agents_table.pop(agent_name, None)
        self.access_times.pop(agent_name, None)

    def evict_lru_agent_networks(self):
        """
        Remove least recently used agent networks to bring storage size under max_items limit.
        """
        if self.max_items <= 0:
            return

        evicted: List[str] = []
        with self.lock:
            overflow: int = len(self.agents_table) - self.max_items
            if overflow <= self.items_overflow_threshold:
                return
            # Sort by access time, oldest first
            sorted_agents = sorted(self.access_times.items(), key=lambda item: item[1])
            for agent_name, _ in sorted_agents[:overflow]:
                self.remove_agent_network(agent_name)
                evicted.append(agent_name)

        # Notify listeners outside of lock
        for listener in self.listeners:
            for agent_name in evicted:
                listener.agent_removed(agent_name, self)
                self.logger.info("%s: EVICTED (LRU) network for agent %s", self._name, agent_name)

    def get_agent_network_provider(self, agent_name: str) -> AgentNetworkProvider:
        """
        Get AgentNetworkProvider for a specific agent
        :param agent_name: name of an agent
        """
        # Agents and their Reservations are always present or absent together.
        reservation: Reservation = self.reservations_table.get(agent_name, None)
        if reservation is not None:
            # We have a reservation for this agent, but we need to check is it still valid:
            if self.is_expired(reservation):
                # Reservation is expired, so AgentNetwork is gone for good:
                with self.lock:
                    self.remove_agent_network(agent_name)

                # Notify listeners about this state change:
                # do it outside of internal lock
                for listener in self.listeners:
                    listener.agent_removed(agent_name, self)
                    self.logger.info("%s: REMOVED expired network for agent %s", self._name, agent_name)

                # Now if we have a source storage,
                # we rely on it to expire this reservation according to its own schedule.

                # Our agent network no longer exists.
                return None
            # Reservation is still valid, so we can return the AgentNetworkProvider for this agent.
            agent_network: AgentNetwork = self.agents_table.get(agent_name, None)
            if agent_network is not None:
                with self.lock:
                    self.access_times[agent_name] = time.time()
                return FixedAgentNetworkProvider(agent_network)
            return None
        # We don't have a reservation for this agent,
        # so check the source storage if we have one:
        if self.base_storage is not None:
            reservation, agent_network = self.base_storage.get_one_reservation(agent_name)
            if reservation is not None and not self.is_expired(reservation):
                # We have a valid reservation for this agent in the source storage,
                # so return the AgentNetworkProvider for this agent.
                # Also cache this reservation and agent network locally:
                now: float = time.time()
                with self.lock:
                    self.reservations_table[agent_name] = reservation
                    self.agents_table[agent_name] = agent_network
                    self.access_times[agent_name] = now
                # Notify listeners about this state change:
                # do it outside of internal lock
                for listener in self.listeners:
                    listener.agent_added(agent_name, self)
                    self.logger.info("ADDED network for agent %s from %s", agent_name, "base storage")

                # Evict least recently used items if we exceeded the limit
                self.evict_lru_agent_networks()

                return FixedAgentNetworkProvider(agent_network)
        return None
