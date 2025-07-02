
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
from typing import Dict

from grpc import RpcMethodHandler
from grpc import unary_stream_rpc_method_handler
from grpc import unary_unary_rpc_method_handler

import neuro_san.api.grpc.agent_pb2 as agent__pb2
from neuro_san.api.grpc.agent_pb2_grpc import AgentServiceServicer


class AgentServicerToServer:
    """
    Taken from generated gRPC code from the agent_pb2_grpc.py file
    so multiple services of the same service protobuf construction can be serviced
    by the same server with a simple addition of an agent name in the gRPC path.
    """

    def __init__(self, servicer: AgentServiceServicer):
        """
        Constructor
        """
        self.servicer: AgentServiceServicer = servicer

    def build_rpc_handlers(self):
        """
        Constructs a table of RpcMethodHandlers
        to be used for an agent service
        """
        # One entry for each grpc method defined in the agent handling protobuf
        # Note that all methods (as of 8/27/2024) are unary_unary.
        # (Watch generated _grpc.py for changes).
        # pylint: disable=no-member
        rpc_method_handlers: Dict[str, RpcMethodHandler] = {
            'Function': unary_unary_rpc_method_handler(
                    self.servicer.Function,
                    request_deserializer=agent__pb2.FunctionRequest.FromString,
                    response_serializer=agent__pb2.FunctionResponse.SerializeToString,
            ),
            'Connectivity': unary_unary_rpc_method_handler(
                    self.servicer.Connectivity,
                    request_deserializer=agent__pb2.ConnectivityRequest.FromString,
                    response_serializer=agent__pb2.ConnectivityResponse.SerializeToString,
            ),
            'StreamingChat': unary_stream_rpc_method_handler(
                    self.servicer.StreamingChat,
                    request_deserializer=agent__pb2.ChatRequest.FromString,
                    response_serializer=agent__pb2.ChatResponse.SerializeToString,
            ),
        }
        return rpc_method_handlers
