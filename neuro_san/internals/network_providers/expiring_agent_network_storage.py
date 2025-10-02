# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from typing import Any
from typing import Dict
from typing import List

import time

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.reservations_storage import ReservationsStorage
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage


class ExpiringAgentNetworkStorage(AgentNetworkStorage, ReservationsStorage):
    """
    An AgentNetworkStorage instance where AgentNetworks are allowed to expire.
    """

    def __init__(self):
        """
        Constructor
        """
        super().__init__()
        self.reservations_table: Dict[str, Reservation] = {}
        self.last_modified: float = 0.0

    def set_sync_target(self, sync_target: ReservationsStorage):
        """
        :param sync_target: The ReservationsStorage where in-memory versions end up
        """
        # We don't need one of these

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

            self.last_modified = time.time()

        # Notify listeners about this state change:
        # do it outside of internal lock
        for listener in self.listeners:
            for agent_name in added:
                listener.agent_added(agent_name, self)
                self.logger.info("ADDED network for agent %s from %s", agent_name, source)
            for agent_name in replaced:
                listener.agent_modified(agent_name, self)
                self.logger.info("REPLACED network for agent %s from %s", agent_name, source)

    def sync_reservations(self):
        """
        Sync Reservations with some underlying data source
        """
        # Nothing to do here.  We are our own source of truth.

    def expire_reservations(self):
        """
        Remove Reservations that are expired
        """

        # First determine what has expired
        now: float = time.time()
        expired: List[str] = []

        for agent_name, reservation in self.reservations_table.items():
            if now > reservation.get_expiration_time_in_seconds():
                expired.append(agent_name)

        # Nothing to do?
        if len(expired) == 0:
            return

        # Do the dirty deeds.
        with self.lock:
            for agent_name in expired:
                self.reservations_table.pop(agent_name, None)
                self.agents_table.pop(agent_name, None)

            self.last_modified = time.time()

        # Notify listeners about this state change:
        # do it outside of internal lock
        for listener in self.listeners:
            for agent_name in expired:
                listener.agent_removed(agent_name, self)
                self.logger.info("REMOVED network for agent %s", agent_name)
