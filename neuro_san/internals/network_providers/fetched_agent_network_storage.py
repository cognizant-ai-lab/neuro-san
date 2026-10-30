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

from typing_extensions import override

from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage


class FetchedAgentNetworkStorage(AgentNetworkStorage):
    """
    AgentNetworkStorage implementation where AgentNetworks' names are full URLs
    and their contents are fetched from the network.
    """

    @override
    async def async_get_agent_network_provider(self, agent_name: str) -> AgentNetworkProvider:
        """
        Get AgentNetworkProvider for a specific agent

        :param agent_name: name of an agent
        """
        # Use the synchronous version on the super class to maybe return what was already cached.
        network_provider: AgentNetworkProvider = super().get_agent_network_provider(agent_name)
        if network_provider is not None:
            return network_provider

        return network_provider
