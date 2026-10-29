
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

from typing import Dict
from typing import List

from neuro_san.internals.graph.registry.agent_network import AgentNetwork


class AgentNetworkStorageManager:
    """
    Interface for an entity managing the storage of multiple agent networks.
    """

    def add_agent_network(self, agent_name: str, agent_network: AgentNetwork):
        """
        This method is a single point of entry in the service
        where we register a new agent name -> AgentNetwork pair.

        :param agent_name: name of an agent
        :param agent_network: An agent network
        """
        raise NotImplementedError

    def remove_agent_network(self, agent_name: str):
        """
        Remove agent name and its AgentNetwork from service scope.

        :param agent_name: name of an agent
        """
        raise NotImplementedError

    def setup_agent_networks(self, agent_networks: Dict[str, AgentNetwork]):
        """
        Replace agents networks with a new collection.
        Previous state could be empty.

        :param agent_networks: A dictionary of agent name -> AgentNetwork
        """
        raise NotImplementedError

    def get_agent_names(self) -> List[str]:
        """
        :return: The list of agent names being managed by the implementation.
        """
        raise NotImplementedError
