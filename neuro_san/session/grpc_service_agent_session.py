
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
from typing import Generator

from leaf_common.session.abstract_service_session import AbstractServiceSession
from leaf_common.time.timeout import Timeout

from neuro_san.api.grpc import agent_pb2 as service_messages
from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.session.agent_service_stub import AgentServiceStub


class GrpcServiceAgentSession(AbstractServiceSession, AgentSession):
    """
    Implementation of AgentSession that talks to a
    gRPC service.  This is largely only used by command-line tests.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, host: str = None,
                 port: str = None,
                 timeout_in_seconds: int = 30,
                 metadata: Dict[str, str] = None,
                 security_cfg: Dict[str, Any] = None,
                 umbrella_timeout: Timeout = None,
                 streaming_timeout_in_seconds: int = None,
                 agent_name: str = None):
        """
        Creates a AgentSession that connects to the
        Agent Service and delegates its implementations to the service.

        :param host: the service host to connect to
                        If None, will use a default
        :param port: the service port
                        If None, will use a default
        :param timeout_in_seconds: timeout to use when communicating
                        with the service
        :param metadata: A grpc metadata of key/value pairs to be inserted into
                         the header. Default is None. Preferred format is a
                         dictionary of string keys to string values.
        :param security_cfg: An optional dictionary of parameters used to
                        secure the TLS and the authentication of the gRPC
                        connection.  Supplying this implies use of a secure
                        GRPC Channel.  Default is None, uses insecure channel.
        :param umbrella_timeout: A Timeout object under which the length of all
                        looping and retries should be considered
        :param streaming_timeout_in_seconds: timeout to use when streaming to/from
                        the service. Default is None, indicating connection should
                        stay open until the (last) result is yielded.
        :param agent_name: The name of the agent to talk to
        """
        use_host: str = "localhost"
        if host is not None:
            use_host = host

        use_port: str = str(self.DEFAULT_PORT)
        if port is not None:
            use_port = port

        # Normally we pass around the service_stub like a class,
        # but AgentServiceStub has a __call__() method to intercept
        # constructor-like behavior.
        if agent_name is None:
            raise ValueError("agent_name is None")
        service_stub = AgentServiceStub(agent_name)
        AbstractServiceSession.__init__(self, "Agent Server",
                                        service_stub,
                                        use_host, use_port,
                                        timeout_in_seconds, metadata,
                                        security_cfg, umbrella_timeout,
                                        streaming_timeout_in_seconds)

    def function(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the FunctionRequest
                    protobufs structure. Has the following keys:
                        <None>
        :return: A dictionary version of the FunctionResponse
                    protobufs structure. Has the following keys:
                "function" - the dictionary description of the function
        """
        # pylint: disable=no-member
        response: Dict[str, Any] = self.call_grpc_method(
            "function",
            self._function_from_stub,
            request_dict,
            service_messages.FunctionRequest())

        Timeout.check_if_not_none(self.umbrella_timeout)
        return response

    def connectivity(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the ConnectivityRequest
                    protobufs structure. Has the following keys:
                        <None>
        :return: A dictionary version of the ConnectivityResponse
                    protobufs structure. Has the following keys:
                "connectivity_info" - the list of connectivity descriptions for
                                    each node in the agent network the service
                                    wants the client ot know about.
        """
        # pylint: disable=no-member
        response: Dict[str, Any] = self.call_grpc_method(
            "connectivity",
            self._connectivity_from_stub,
            request_dict,
            service_messages.ConnectivityRequest())

        Timeout.check_if_not_none(self.umbrella_timeout)
        return response

    def streaming_chat(self, request_dict: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
        """
        :param request_dict: A dictionary version of the ChatRequest
                    protobufs structure. Has the following keys:
            "user_message" - A ChatMessage dict representing the user input to the chat stream
            "chat_context" - A ChatContext dict representing the state of the previous conversation
                            (if any)
        :return: An iterator of dictionary versions of the ChatResponse
                    protobufs structure. Has the following keys:
            "response"      - An optional ChatMessage dictionary.  See chat.proto for details.

            Note that responses to the chat input might be numerous and will come as they
            are produced until the system decides there are no more messages to be sent.
        """
        # pylint: disable=no-member
        return self.call_grpc_method(
            "streaming_chat",
            self._streaming_chat_from_stub,
            request_dict,
            request_instance=service_messages.ChatRequest(),
            stream_response=True)

    @staticmethod
    def _function_from_stub(stub, timeout_in_seconds,
                            metadata, credentials, *args):
        """
        Global method associated with the session that calls Function
        given a grpc Stub already set up with a channel (socket) to call with.
        """
        response = stub.Function(*args, timeout=timeout_in_seconds,
                                 metadata=metadata,
                                 credentials=credentials)
        return response

    @staticmethod
    def _connectivity_from_stub(stub, timeout_in_seconds,
                                metadata, credentials, *args):
        """
        Global method associated with the session that calls Connectivity
        given a grpc Stub already set up with a channel (socket) to call with.
        """
        response = stub.Connectivity(*args, timeout=timeout_in_seconds,
                                     metadata=metadata,
                                     credentials=credentials)
        return response

    @staticmethod
    def _streaming_chat_from_stub(stub, timeout_in_seconds,
                                  metadata, credentials, *args):
        """
        Global method associated with the session that calls StreamingChat
        given a grpc Stub already set up with a channel (socket) to call with.
        """
        response = stub.StreamingChat(*args, timeout=timeout_in_seconds,
                                      metadata=metadata,
                                      credentials=credentials)
        return response
