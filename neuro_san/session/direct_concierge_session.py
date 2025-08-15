
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

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.interfaces.concierge_session import ConciergeSession
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage


class DirectConciergeSession(ConciergeSession):
    """
    Service-agnostic guts for a ConciergeSession.
    This could be used by a gRPC and/or Http service.
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
                        secure the TLS and the authentication of the gRPC
                        connection.  Supplying this implies use of a secure
                        GRPC Channel.  If None, uses insecure channel.
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
