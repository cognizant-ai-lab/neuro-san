
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
from typing import Iterator

import json
import grpc

from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import Parse

from leaf_server_common.server.grpc_metadata_forwarder import GrpcMetadataForwarder
from leaf_server_common.server.request_logger import RequestLogger

from neuro_san.api.grpc import agent_pb2 as service_messages
from neuro_san.api.grpc import agent_pb2_grpc
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.service.generic.agent_server_logging import AgentServerLogging
from neuro_san.service.generic.agent_service_provider import AgentServiceProvider
from neuro_san.service.generic.agent_service import AgentService
from neuro_san.service.utils.service_context import ServiceContext


class GrpcAgentService(agent_pb2_grpc.AgentServiceServicer):
    """
    A gRPC implementation of the Neuro-San Agent Service.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self,
                 request_logger: RequestLogger,
                 security_cfg: Dict[str, Any],
                 agent_name: str,
                 agent_network_provider: AgentNetworkProvider,
                 server_logging: AgentServerLogging,
                 service_context: ServiceContext):
        """
        Set the gRPC interface up for health checking so that the service
        will be opened to callers when the mesh sees it operational, if this
        is not done the mesh will treat the service instance as non-functional

        :param request_logger: The instance of the RequestLogger that helps
                    keep track of stats
        :param security_cfg: A dictionary of parameters used to
                        secure the TLS and the authentication of the gRPC
                        connection.  Supplying this implies use of a secure
                        GRPC Channel.  If None, uses insecure channel.
        :param agent_name: The agent name for the service
        :param agent_network_provider: The AgentNetworkProvider to use for the service.
        :param server_logging: An AgentServerLogging instance initialized so that
                        spawned asyncrhonous threads can also properly initialize
                        their logging.
        :param service_context: The ServiceContext object containing global-ish state
        """
        self.forwarder: GrpcMetadataForwarder = server_logging.get_forwarder()
        self.service_provider: AgentServiceProvider =\
            AgentServiceProvider(
                request_logger,
                security_cfg,
                agent_name,
                agent_network_provider,
                server_logging,
                service_context)

    def get_request_count(self) -> int:
        """
        :return: The number of currently active requests
        """
        if not self.service_provider.service_created():
            # Service is not yet instantiated - it has no requests
            return 0
        service: AgentService = self.service_provider.get_service()
        return service.get_request_count()

    # pylint: disable=no-member
    def Function(self, request: service_messages.FunctionRequest,
                 context: grpc.ServicerContext) \
            -> service_messages.FunctionResponse:
        """
        Allows a client to get the outward-facing function for the agent
        served by this service.

        :param request: a FunctionRequest
        :param context: a grpc.ServicerContext
        :return: a FunctionResponse
        """
        request_metadata: Dict[str, Any] = self.forwarder.forward(context)

        # Get our args in order to pass to grpc-free session level
        request_dict: Dict[str, Any] = MessageToDict(request)
        service: AgentService = self.service_provider.get_service()
        response_dict: Dict[str, Any] =\
            service.function(request_dict, request_metadata, context)

        # Convert the response dictionary to a grpc message
        response_string = json.dumps(response_dict)
        response = service_messages.FunctionResponse()
        Parse(response_string, response)
        return response

    # pylint: disable=no-member
    def Connectivity(self, request: service_messages.ConnectivityRequest,
                     context: grpc.ServicerContext) \
            -> service_messages.ConnectivityResponse:
        """
        Allows a client to get connectivity information for the agent
        served by this service.

        :param request: a ConnectivityRequest
        :param context: a grpc.ServicerContext
        :return: a ConnectivityResponse
        """
        request_metadata: Dict[str, Any] = self.forwarder.forward(context)

        # Get our args in order to pass to grpc-free session level
        request_dict: Dict[str, Any] = MessageToDict(request)
        service: AgentService = self.service_provider.get_service()
        response_dict: Dict[str, Any] = service.connectivity(request_dict, request_metadata, context)

        # Convert the response dictionary to a grpc message
        response_string = json.dumps(response_dict)
        response = service_messages.ConnectivityResponse()
        Parse(response_string, response)
        return response

    def StreamingChat(self, request: service_messages.ChatRequest,
                      context: grpc.ServicerContext) \
            -> Iterator[service_messages.ChatResponse]:
        """
        Initiates or continues the agent chat with the session_id
        context in the request.

        :param request: a ChatRequest
        :param context: a grpc.ServicerContext
        :return: an iterator for (eventually) returned ChatResponses
        """
        request_metadata: Dict[str, Any] = self.forwarder.forward(context)

        # Get our args in order to pass to grpc-free session level
        request_dict: Dict[str, Any] = MessageToDict(request)
        service: AgentService = self.service_provider.get_service()
        response_dict_iterator: Iterator[Dict[str, Any]] =\
            service.streaming_chat(request_dict, request_metadata, context)
        for response_dict in response_dict_iterator:
            # Convert the response dictionary to a grpc message
            response_string = json.dumps(response_dict)
            response = service_messages.ChatResponse()
            Parse(response_string, response)
            # Yield-ing a single response allows one response to be returned
            # over the connection while keeping it open to wait for more.
            # Grpc client code handling response streaming knows to construct an
            # iterator on its side to do said waiting over there.
            yield response
