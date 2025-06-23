
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
from typing import List

from asyncio import Future
from copy import copy

from leaf_common.asyncio.async_to_sync_generator import AsyncToSyncGenerator
from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor
from leaf_common.time.timeout import Timeout

from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.internals.chat.connectivity_reporter import ConnectivityReporter
from neuro_san.internals.chat.data_driven_chat_session import DataDrivenChatSession
from neuro_san.internals.filters.message_filter import MessageFilter
from neuro_san.internals.filters.message_filter_factory import MessageFilterFactory
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.session.session_invocation_context import SessionInvocationContext


class DirectAgentSession(AgentSession):
    """
    Service-agnostic guts for a AgentSession.
    This could be used by a Flask/Quart app or a gRPC service.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self,
                 agent_network: AgentNetwork,
                 invocation_context: SessionInvocationContext,
                 metadata: Dict[str, Any] = None,
                 security_cfg: Dict[str, Any] = None,
                 umbrella_timeout: Timeout = None):
        """
        Constructor

        :param agent_network: The AgentNetwork to use for the session.
        :param invocation_context: The SessionInvocationContext to use to consult
                        for policy objects scoped at the invocation level.
        :param metadata: A dictionary of request metadata to be forwarded
                        to subsequent yet-to-be-made requests.
        :param security_cfg: A dictionary of parameters used to
                        secure the TLS and the authentication of the gRPC
                        connection.  Supplying this implies use of a secure
                        GRPC Channel.  If None, uses insecure channel.
        :param umbrella_timeout: A Timeout object to periodically check in loops.
                        Default is None (no timeout).
        """
        # These aren't used yet
        self._metadata: Dict[str, Any] = metadata
        self._security_cfg: Dict[str, Any] = security_cfg

        self.invocation_context: SessionInvocationContext = invocation_context
        self.agent_network: AgentNetwork = agent_network
        self.request_id: str = None
        self.umbrella_timeout: Timeout = umbrella_timeout
        if metadata is not None:
            self.request_id = metadata.get("request_id")

    def function(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the FunctionRequest
                    protobufs structure. Has the following keys:
                        <None>
        :return: A dictionary version of the FunctionResponse
                    protobufs structure. Has the following keys:
                "function" - the dictionary description of the function
        """
        _ = request_dict
        response_dict: Dict[str, Any] = {
        }

        front_man: str = self.agent_network.find_front_man()
        if front_man is not None:
            spec: Dict[str, Any] = self.agent_network.get_agent_tool_spec(front_man)
            empty: Dict[str, Any] = {}
            function: Dict[str, Any] = spec.get("function", empty)
            response_dict = {
                "function": function,
            }

        return response_dict

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
        _ = request_dict
        response_dict: Dict[str, Any] = {
        }

        reporter = ConnectivityReporter(self.agent_network)
        agent_toolbox_info_file: str = self.agent_network.get_agent_toolbox_info_file()
        connectivity_info: List[Dict[str, Any]] = reporter.report_network_connectivity(agent_toolbox_info_file)
        response_dict = {
            "connectivity_info": connectivity_info,
        }

        return response_dict

    # pylint: disable=too-many-locals,too-many-statements,too-many-branches
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
        extractor = DictionaryExtractor(request_dict)

        # Get the user input.
        user_input = extractor.get("user_message.text")

        # Create the gateway to the internals.
        chat_session = DataDrivenChatSession(agent_network=self.agent_network)

        # Prepare the response dictionary
        template_response_dict = {
        }

        if chat_session is None or user_input is None:
            # Can't go on to chat, so report back early with a single value.
            # There is no ChatMessage response in the dictionary in this case
            yield template_response_dict
            return

        # Create a message filter so as to minimize network traffic per what the user wants
        chat_filter: Dict[str, Any] = request_dict.get("chat_filter")
        message_filter: MessageFilter = MessageFilterFactory.create_message_filter(chat_filter)

        chat_context: Dict[str, Any] = request_dict.get("chat_context")
        sly_data: Dict[str, Any] = request_dict.get("sly_data")

        # Create an asynchronous background task to process the user input.
        # This might take a few minutes, which can be longer than some
        # sockets stay open.
        asyncio_executor: AsyncioExecutor = self.invocation_context.get_asyncio_executor()
        future: Future = asyncio_executor.submit(self.request_id, chat_session.streaming_chat,
                                                 user_input, self.invocation_context, sly_data,
                                                 chat_context)
        # Ignore the future. Live in the now.
        _ = future

        # The synchronously_iterate() method below will synchronously block waiting for
        # chat.ChatMessage dictionaries to come back asynchronously from the submit()
        # above until there are no more from the input.
        empty: Dict[str, Any] = {}
        generator = AsyncToSyncGenerator(asyncio_executor, self.request_id,
                                         generated_type=Dict,
                                         keep_alive_result=empty,
                                         keep_alive_timeout_seconds=10.0,
                                         umbrella_timeout=self.umbrella_timeout)
        for message in generator.synchronously_iterate(self.invocation_context.get_queue()):

            response_dict: Dict[str, Any] = copy(template_response_dict)
            if message_filter.allow(message):
                # We expect the message to be a dictionary form of chat.ChatMessage
                response_dict["response"] = message
                yield response_dict

    def reset(self):
        """
        Allows for re-use of the same instance for clients
        """
        self.invocation_context.reset()

    def close(self):
        """
        Tears down resources created
        """
        if self.invocation_context is None:
            return
        self.invocation_context.close()
        self.invocation_context = None
