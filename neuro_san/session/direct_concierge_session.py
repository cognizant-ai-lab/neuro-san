
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

from neuro_san.interfaces.concierge_session import ConciergeSession
from neuro_san.internals.network_providers.service_agent_network_storage import ServiceAgentNetworkStorage


class DirectConciergeSession(ConciergeSession):
    """
    Service-agnostic guts for a ConciergeSession.
    This could be used by a gRPC and/or Http service.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self,
                 metadata: Dict[str, Any] = None,
                 security_cfg: Dict[str, Any] = None):
        """
        Constructor

        :param metadata: A dictionary of request metadata to be forwarded
                        to subsequent yet-to-be-made requests.
        :param security_cfg: A dictionary of parameters used to
                        secure the TLS and the authentication of the gRPC
                        connection.  Supplying this implies use of a secure
                        GRPC Channel.  If None, uses insecure channel.
        """
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
        network_storage: ServiceAgentNetworkStorage = ServiceAgentNetworkStorage.get_instance()
        agents_names: List[str] = network_storage.get_agent_names()
        agents_list: List[Dict[str, Any]] = []
        for agent_name in agents_names:
            agents_list.append({"agent_name": agent_name, "description": ""})
        return {"agents": agents_list}
