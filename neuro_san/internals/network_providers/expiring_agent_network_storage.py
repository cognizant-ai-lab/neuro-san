
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
from typing import Tuple

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.interfaces.reservations_storage import ReservationsStorage
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.network_providers.abstract_reservations_storage \
    import AbstractReservationsStorage
from neuro_san.internals.network_providers.fixed_agent_network_provider import FixedAgentNetworkProvider


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
        super().__init__(check_expirations_interval_seconds=check_expirations_interval_seconds)
        self.reservations_table: Dict[str, Reservation] = {}
        self.base_storage: ReservationsStorage = None

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

    def start(self):
        """
        Start this storage, which includes starting the expiration checking loop.
        """
        super().start()
        if self.base_storage is not None:
            self.base_storage.start()

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
        with self.lock:
            for reservation, agent_spec in reservations_dict.items():

                agent_name: str = reservation.get_reservation_id()
                is_new = self.agents_table.get(agent_name) is None

                agent_network = AgentNetwork(agent_spec, agent_name)
                self.agents_table[agent_name] = agent_network
                self.reservations_table[agent_name] = reservation

                if is_new:
                    added.append(agent_name)
                else:
                    replaced.append(agent_name)

        # Notify listeners about this state change:
        # do it outside of internal lock
        for listener in self.listeners:
            for agent_name in added:
                listener.agent_added(agent_name, self)
                self.logger.info("ADDED network for agent %s from %s", agent_name, source)
            for agent_name in replaced:
                listener.agent_modified(agent_name, self)
                self.logger.info("REPLACED network for agent %s from %s", agent_name, source)

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
            if reservation.is_expired():
                expired.append(agent_name)

        # Nothing to do?
        if len(expired) == 0:
            return

        # Do the dirty deeds.
        with self.lock:
            for agent_name in expired:
                self.reservations_table.pop(agent_name, None)
                self.agents_table.pop(agent_name, None)

        # Notify listeners about this state change:
        # do it outside of internal lock
        for listener in self.listeners:
            for agent_name in expired:
                listener.agent_removed(agent_name, self)
                self.logger.info("REMOVED network for agent %s", agent_name)

    def get_agent_network_provider(self, agent_name: str) -> AgentNetworkProvider:
        """
        Get AgentNetworkProvider for a specific agent
        :param agent_name: name of an agent
        """
        # Agents and their Reservations are always present or absent together.
        reservation: Reservation = self.reservations_table.get(agent_name, None)
        if reservation is not None:
            # We have a reservation for this agent, but we need to check is it still valid:
            if reservation.is_expired():
                # Reservation is expired, so AgentNetwork is gone for good:
                with self.lock:
                    self.reservations_table.pop(agent_name, None)
                    self.agents_table.pop(agent_name, None)

                # Notify listeners about this state change:
                # do it outside of internal lock
                for listener in self.listeners:
                    listener.agent_removed(agent_name, self)
                    self.logger.info("REMOVED expired network for agent %s", agent_name)

                # Now if we have a source storage,
                # we rely on it to expire this reservation according to its own schedule.

                # Our agent network no longer exists.
                return None
            # Reservation is still valid, so we can return the AgentNetworkProvider for this agent.
            agent_network: AgentNetwork = self.agents_table.get(agent_name, None)
            if agent_network is not None:
                return FixedAgentNetworkProvider(agent_network)
            return None
        # We don't have a reservation for this agent,
        # so check the source storage if we have one:
        if self.base_storage is None:
            print(f">>>>>>>>>>>>>>>>>Agent {agent_name} not found in local storage, and no base storage to check.")
        if self.base_storage is not None:
            print(f">>>>>>>>>>>>>>>>>Agent {agent_name} not found in local storage, checking base storage...")
            reservation, agent_network = self.base_storage.get_one_reservation(agent_name)
            print(f">>>>>>>>>>>>>>>>>Got reservation {reservation} and agent_network {agent_network} from base storage for agent {agent_name}")
            if reservation is not None and not reservation.is_expired():
                # We have a valid reservation for this agent in the source storage,
                # so return the AgentNetworkProvider for this agent.
                # Also cache this reservation and agent network locally:
                with self.lock:
                    self.reservations_table[agent_name] = reservation
                    self.agents_table[agent_name] = agent_network
                # Notify listeners about this state change:
                # do it outside of internal lock
                for listener in self.listeners:
                    listener.agent_added(agent_name, self)
                    self.logger.info("ADDED network for agent %s from %s", agent_name, "base storage")

                return FixedAgentNetworkProvider(agent_network)
        return None
