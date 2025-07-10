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

from typing import Dict
from typing import List

import logging
import threading
import time

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.interfaces.agent_state_listener import AgentStateListener
from neuro_san.internals.network_providers.single_agent_network_provider import SingleAgentNetworkProvider


class AgentNetworkStorage:
    """
    Service-wide storage for AgentNetworkProviders containing
    a table of currently active AgentNetworks for each agent registered to the service.
    Note: a mapping from an agent to its AgentNetwork is dynamic,
          as it is possible to change agents definitions at service run-time.
    """

    def __init__(self):
        self.agents_table: Dict[str, AgentNetwork] = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.lock = threading.Lock()
        self.listeners: List[AgentStateListener] = []
        self.last_modified: float = time.time()

    def add_listener(self, listener: AgentStateListener):
        """
        Add a state listener to be notified when status of service agents changes.
        """
        self.listeners.append(listener)

    def remove_listener(self, listener: AgentStateListener):
        """
        Remove a state listener from registered set.
        """
        if listener in self.listeners:
            self.listeners.remove(listener)

    def add_agent_network(self, agent_name: str, agent_network: AgentNetwork):
        """
        This method is a single point of entry in the service
        where we register a new agent name -> AgentNetwork pair in the service scope
        or notify the service that for existing agent its AgentNetwork has been modified.
        """
        is_new: bool = False
        with self.lock:
            is_new = self.agents_table.get(agent_name) is None
            self.agents_table[agent_name] = agent_network
            self.last_modified = time.time()

        # Notify listeners about this state change:
        # do it outside of internal lock
        for listener in self.listeners:
            if is_new:
                listener.agent_added(agent_name)
                self.logger.info("ADDED network for agent %s", agent_name)
            else:
                listener.agent_modified(agent_name)
                self.logger.info("REPLACED network for agent %s", agent_name)

    def setup_agent_networks(self, agent_networks: Dict[str, AgentNetwork]):
        """
        Replace agents networks with a new collection.
        Previous state could be empty.
        """
        current_agents = set(self.agents_table.keys())
        new_agents = set(agent_networks.keys())
        # Remove agents which are not in the new collection:
        agents_to_remove = current_agents - new_agents
        for agent_name in agents_to_remove:
            self.remove_agent_network(agent_name)
        # Now add (or possibly replace) agents from new collection:
        for agent_name in new_agents:
            self.add_agent_network(agent_name, agent_networks[agent_name])

    def remove_agent_network(self, agent_name: str):
        """
        Remove agent name and its AgentNetwork from service scope,
        so that agent becomes unavailable on our server.
        """
        with self.lock:
            self.agents_table.pop(agent_name, None)
            self.last_modified = time.time()

        # Notify listeners about this state change:
        # do it outside of internal lock
        for listener in self.listeners:
            listener.agent_removed(agent_name)
        self.logger.info("REMOVED network for agent %s", agent_name)

    def get_agent_network_provider(self, agent_name: str) -> AgentNetworkProvider:
        """
        Get AgentNetworkProvider for a specific agent
        :param agent_name: name of an agent
        """
        return SingleAgentNetworkProvider(agent_name, self.agents_table)

    def get_agent_names(self) -> List[str]:
        """
        Return static list of agent names.
        """
        with self.lock:
            # Create static snapshot of agents names collection
            return list(self.agents_table.keys())

    def get_last_modified(self) -> float:
        """
        :return: A float timestamp from time.time() as to when the instance was last modified.
        """
        return self.last_modified
