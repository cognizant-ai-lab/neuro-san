
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
from __future__ import annotations

from typing import Dict
from typing import List
from typing import Set
from typing import Type
from types import TracebackType

from logging import getLogger
from logging import Logger
from threading import RLock

from typing_extensions import override

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.interfaces.agent_state_listener import AgentStateListener
from neuro_san.internals.interfaces.agent_storage_source import AgentStorageSource
from neuro_san.internals.interfaces.listenable import Listenable
from neuro_san.internals.network_providers.agent_network_storage_manager import AgentNetworkStorageManager
from neuro_san.internals.network_providers.single_agent_network_provider import SingleAgentNetworkProvider


class AgentNetworkStorage(AgentStorageSource, AgentNetworkStorageManager, Listenable[AgentStateListener]):
    """
    Service-wide storage for AgentNetworkProviders containing
    a table of currently active AgentNetworks for each agent registered to the service.
    Note: a mapping from an agent to its AgentNetwork is dynamic,
          as it is possible to change agents definitions at service run-time.
    """

    def __init__(self):
        self.agents_table: Dict[str, AgentNetwork] = {}
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.lock: RLock = RLock()
        self.listeners: List[AgentStateListener] = []

    @override
    def add_listener(self, listener: AgentStateListener):
        """
        Add a state listener to be notified when status of service agents changes.

        :param listener: listener of type AgentStateListener to be added
        """
        self.listeners.append(listener)

    @override
    def remove_listener(self, listener: AgentStateListener):
        """
        Remove a state listener from registered set.

        :param listener: listener of type AgentStateListener to be removed
        """
        if listener in self.listeners:
            self.listeners.remove(listener)

    @override
    def get_listeners(self) -> List[AgentStateListener]:
        """
        :return: a list of AgentStateListeners that are listening.
        """
        return list(self.listeners)

    @override
    def add_agent_network(self, agent_name: str, agent_network: AgentNetwork):
        """
        This method is a single point of entry in the service
        where we register a new agent name -> AgentNetwork pair in the service scope
        or notify the service that for existing agent its AgentNetwork has been modified.
        """
        is_new: bool = False
        with self.lock:
            test_agent_network: AgentNetwork = self.get_without_lock(agent_name)
            is_new = test_agent_network is None
            self.put_without_lock(agent_name, agent_network)

        agent_size_in_bytes: int = agent_network.get_size_in_bytes()

        # Notify listeners about this state change:
        # do it outside of internal lock
        listener: AgentStateListener = None
        for listener in self.listeners:
            if is_new:
                listener.agent_added(agent_name, self)
                self.logger.info("ADDED network for agent %s (%d bytes): %d",
                                 agent_name, agent_size_in_bytes, id(agent_network))
            else:
                listener.agent_modified(agent_name, self)
                self.logger.info("REPLACED network for agent %s (%d bytes): %d",
                                 agent_name, agent_size_in_bytes, id(agent_network))

    @override
    def setup_agent_networks(self, agent_networks: Dict[str, AgentNetwork]):
        """
        Replace agents networks with a new collection.
        Previous state could be empty.
        """
        current_agents: Set[str] = set(self.agents_table.keys())
        new_agents: Set[str] = set(agent_networks.keys())
        # Remove agents which are not in the new collection:
        agents_to_remove: Set[str] = current_agents - new_agents
        agent_name: str = None
        for agent_name in agents_to_remove:
            self.remove_agent_network(agent_name)
        # Now add (or possibly replace) agents from new collection:
        for agent_name in new_agents:
            self.add_agent_network(agent_name, agent_networks[agent_name])

    @override
    def remove_agent_network(self, agent_name: str):
        """
        Remove agent name and its AgentNetwork from service scope,
        so that agent becomes unavailable on our server.
        """
        agent_network: AgentNetwork = None
        with self.lock:
            agent_network = self.get_without_lock(agent_name)
            self.agents_table.pop(agent_name, None)

        # Notify listeners about this state change:
        # do it outside of internal lock
        listener: AgentStateListener = None
        for listener in self.listeners:
            listener.agent_removed(agent_name, self)
        # We can log id(None) if necessary - that's a legal value
        self.logger.info("REMOVED network for agent %s : %d", agent_name, id(agent_network))

    @override
    def get_agent_network_provider(self, agent_name: str) -> AgentNetworkProvider:
        """
        Get AgentNetworkProvider for a specific agent
        :param agent_name: name of an agent
        """
        return SingleAgentNetworkProvider(agent_name, self.agents_table)

    @override
    def get_agent_names(self) -> List[str]:
        """
        Return static list of agent names.
        """
        with self.lock:
            # Create static snapshot of agents names collection
            return list(self.agents_table.keys())

    def __enter__(self) -> AgentNetworkStorage:
        """
        Enter use of the instance's agents_table holding the lock
        :return: The instance
        """
        self.lock.acquire()
        return self

    def get_without_lock(self, agent_name: str) -> AgentNetwork:
        """
        :param agent_name: name of an agent
        :return: Current AgentNetwork instance for specific agent name.
                None if this does not exist for the instance's agent_name.
        """
        return self.agents_table.get(agent_name, None)

    def put_without_lock(self, agent_name: str, agent_network: AgentNetwork):
        """
        :param agent_name: name of an agent
        :param agent_network: AgentNetwork corresponding to the name
        """
        self.agents_table[agent_name] = agent_network

    def remove_without_lock(self, agent_name: str):
        """
        :param agent_name: name of an agent to remove
        """
        self.agents_table.pop(agent_name, None)

    def __exit__(self, exc_type: Type[BaseException], exc_value: BaseException, traceback: TracebackType) -> bool:
        """
        :param exc_type: The type of the exception that was raised
        :param exc_value: The exception instance
        :param traceback: The traceback
        :return: True to suppress exception. False or None to propagate exception.
        """
        self.lock.release()
        return False
