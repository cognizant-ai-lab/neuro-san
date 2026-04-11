
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

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider


class FixedAgentNetworkProvider(AgentNetworkProvider):
    """
    Class providing fixed immutable AgentNetwork for a given agent in the service scope.
    """
    def __init__(self, agent_network: AgentNetwork):
        """
        Constructor.
        :param agent_network: AgentNetwork instance to be returned by this provider.
        """
        self.agent_network: AgentNetwork = agent_network

    def get_agent_network(self) -> AgentNetwork:
        """
        :return: Current AgentNetwork instance for specific agent name.
        """
        return self.agent_network
