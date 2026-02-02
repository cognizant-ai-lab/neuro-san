
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

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.interfaces.concierge_session import ConciergeSession
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage


class DirectConciergeSession(ConciergeSession):
    """
    Service-agnostic guts for a ConciergeSession.
    This could be used by an HTTP service.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self,
                 network_storage: AgentNetworkStorage,
                 metadata: Dict[str, Any] = None,
                 security_cfg: Dict[str, Any] = None):
        """
        Constructor

        :param network_storage: A AgentNetworkStorage instance which keeps all
                                the AgentNetwork instances.
        :param metadata: A dictionary of request metadata to be forwarded
                        to subsequent yet-to-be-made requests.
        :param security_cfg: A dictionary of parameters used to
                        secure the TLS and the authentication of the HTTP
                        connection.  Supplying this implies use of a secure
                        HTTP connection.  If None, uses insecure connection.
        """
        self.network_storage: AgentNetworkStorage = network_storage
        # These aren't used yet
        self._metadata: Dict[str, Any] = metadata
        self._security_cfg: Dict[str, Any] = security_cfg

    def list(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the ConciergeRequest
                    protobuf structure. Has the following keys:
                        <None>
        :return: A dictionary version of the ConciergeResponse
                    protobuf structure. Has the following keys:
                "agents" - the sequence of dictionaries describing available agents
        """
        agents_names: List[str] = self.network_storage.get_agent_names()
        empty_list: List[str] = []

        agents_list: List[Dict[str, Any]] = []
        for agent_name in agents_names:

            # Get the spec for the agent network
            provider: AgentNetworkProvider = self.network_storage.get_agent_network_provider(agent_name)
            agent_network: AgentNetwork = provider.get_agent_network()
            agent_spec: Dict[str, Any] = agent_network.get_config()
            extractor = DictionaryExtractor(agent_spec)

            # It's concievable we could get the description from the front man's function.
            # We haven't done that yet, though, so deferring until a hew and cry emerges.
            description: str = extractor.get("metadata.description", "")
            tags: List[str] = extractor.get("metadata.tags", empty_list)

            # Construct an AgentInfo entry
            agent_info: Dict[str, Any] = {
                "agent_name": agent_name,
                "description": description,
                "tags": tags,
            }
            agents_list.append(agent_info)

        response: Dict[str, Any] = {
            "agents": agents_list
        }
        return response
