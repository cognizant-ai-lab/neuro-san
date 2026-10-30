
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

from abc import abstractmethod

from leaf_common.utils.interface import interface

from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.graph.registry.agent_network import AgentNetwork


@interface
class AgentStorageSource:
    """
    Interface onto AgentNetworkStorage so that there is not a tangle with the service side.
    """

    @abstractmethod
    def get_agent_network_provider(self, agent_name: str) -> AgentNetworkProvider:
        """
        Get AgentNetworkProvider for a specific agent
        :param agent_name: name of an agent
        """
        raise NotImplementedError

    @abstractmethod
    def get_agent_names(self) -> List[str]:
        """
        :return: The list of agent names being managed by the implementation.
        """
        raise NotImplementedError

    @abstractmethod
    def setup_agent_networks(self, agent_networks: Dict[str, AgentNetwork]):
        """
        Replace agents networks with a new collection.
        Previous state could be empty.

        :param agent_networks: A dictionary of agent name -> AgentNetwork
        """
        raise NotImplementedError
