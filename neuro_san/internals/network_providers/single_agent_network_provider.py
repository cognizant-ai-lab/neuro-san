
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

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider


class SingleAgentNetworkProvider(AgentNetworkProvider):
    """
    Class providing current AgentNetwork for a given agent in the service scope.
    """
    def __init__(self, agent_name: str, agents_table: Dict[str, AgentNetwork]):
        """
        Constructor.
        :param agent_name: name of an agent to provide AgentNetwork instances for;
        :param agents_table: service-wide table mapping agent names to their
            currently active AgentNetwork instances.
            This table is assumed to be dynamically modified outside a single agent scope.
        """
        self.agent_name: str = agent_name
        self.agents_table: Dict[str, AgentNetwork] = agents_table

    def get_agent_network(self) -> AgentNetwork:
        """
        :return: Current AgentNetwork instance for specific agent name.
                None if this does not exist for the instance's agent_name.
        """
        return self.agents_table.get(self.agent_name)
