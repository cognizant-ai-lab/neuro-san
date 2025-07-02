
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

import json
import uuid

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor

from leaf_server_common.server.atomic_counter import AtomicCounter

from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.run_context.factory.master_toolbox_factory import MasterToolboxFactory
from neuro_san.internals.run_context.factory.master_llm_factory import MasterLlmFactory
from neuro_san.service.generic.agent_server_logging import AgentServerLogging
from neuro_san.service.generic.chat_message_converter import ChatMessageConverter
from neuro_san.service.interfaces.event_loop_logger import EventLoopLogger
from neuro_san.session.async_direct_agent_session import AsyncDirectAgentSession
from neuro_san.session.external_agent_session_factory import ExternalAgentSessionFactory
from neuro_san.session.session_invocation_context import SessionInvocationContext

# A list of methods to not log requests for
# Some of these can be way too chatty
DO_NOT_LOG_REQUESTS = [
]


# pylint: disable=too-many-instance-attributes
class AsyncAgentService:
    """
    A base implementation of the Neuro-San Async Agent Service,
    independent of target transport protocol.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self,
                 request_logger: EventLoopLogger,
                 security_cfg: Dict[str, Any],
                 agent_name: str,
                 agent_network_provider: AgentNetworkProvider,
                 server_logging: AgentServerLogging):
        """
        :param request_logger: The instance of the EventLoopLogger that helps
                        log information from running event loop
        :param security_cfg: A dictionary of parameters used to
                        secure the TLS and the authentication of the gRPC
                        connection.  Supplying this implies use of a secure
                        GRPC Channel.  If None, uses insecure channel.
        :param agent_name: The agent name for the service
        :param agent_network_provider: The AgentNetworkProvider to use for the session.
        :param server_logging: An AgentServerLogging instance initialized so that
                        spawned asynchronous threads can also properly initialize
                        their logging.
        """
        self.request_logger = request_logger
        self.security_cfg = security_cfg
        self.server_logging: AgentServerLogging = server_logging

        self.agent_network_provider: AgentNetworkProvider = agent_network_provider
        self.agent_name: str = agent_name
        self.request_counter = AtomicCounter()

        agent_network: AgentNetwork = self.agent_network_provider.get_agent_network()
        config: Dict[str, Any] = agent_network.get_config()
        self.llm_factory: ContextTypeLlmFactory = MasterLlmFactory.create_llm_factory(config)
        self.toolbox_factory: ContextTypeToolboxFactory = MasterToolboxFactory.create_toolbox_factory(config)
        # Load once.
        self.llm_factory.load()
        self.toolbox_factory.load()

    def get_request_count(self) -> int:
        """
        :return: The number of currently active requests
        """
        return self.request_counter.get_count()

    async def function(self, request_dict: Dict[str, Any],
                       request_metadata: Dict[str, Any]) \
            -> Dict[str, Any]:
        """
        Allows a client to get the outward-facing function for the agent
        served by this service.

        :param request_dict: a FunctionRequest dictionary
        :param request_metadata: request metadata
        :return: a FunctionResponse dictionary
        """
        self.request_counter.increment()
        do_log: bool = "Function" not in DO_NOT_LOG_REQUESTS
        log_marker: str = "function request"
        metadata: Dict[str, str] = {
            "request_id": f"server-{uuid.uuid4()}"
        }
        metadata.update(request_metadata)
        if do_log:
            self.request_logger.info(
                metadata,
                "Received a %s request for %s",
                f"{self.agent_name}.Function", log_marker)

        # Delegate to Direct*Session
        agent_network: AgentNetwork = self.agent_network_provider.get_agent_network()
        session: AsyncDirectAgentSession =\
            AsyncDirectAgentSession(
                agent_network=agent_network,
                invocation_context=None,
                metadata=metadata,
                security_cfg=self.security_cfg)
        response_dict = await session.function(request_dict)

        if do_log:
            self.request_logger.info(
                metadata,
                "Done with %s request for %s",
                f"{self.agent_name}.Function", log_marker)

        self.request_counter.decrement()
        return response_dict

    async def connectivity(self, request_dict: Dict[str, Any],
                           request_metadata: Dict[str, Any]) \
            -> Dict[str, Any]:
        """
        Allows a client to get connectivity information for the agent
        served by this service.

        :param request_dict: a ChatRequest dictionary
        :param request_metadata: request metadata
        :return: a ConnectivityResponse dictionary
        """
        self.request_counter.increment()
        do_log: bool = "Connectivity" not in DO_NOT_LOG_REQUESTS
        log_marker: str = "connectivity request"
        metadata: Dict[str, str] = {
            "request_id": f"server-{uuid.uuid4()}"
        }
        metadata.update(request_metadata)

        if do_log:
            self.request_logger.info(
                metadata,
                "Received a %s request for %s",
                f"{self.agent_name}.Connectivity", log_marker)

        # Delegate to Direct*Session
        agent_network: AgentNetwork = self.agent_network_provider.get_agent_network()
        session: AsyncDirectAgentSession =\
            AsyncDirectAgentSession(
                agent_network=agent_network,
                invocation_context=None,
                metadata=metadata,
                security_cfg=self.security_cfg)
        response_dict = await session.connectivity(request_dict)

        if do_log:
            self.request_logger.info(
                metadata,
                "Done with %s request for %s",
                f"{self.agent_name}.Connectivity", log_marker)

        self.request_counter.decrement()
        return response_dict

    # pylint: disable=too-many-locals
    async def streaming_chat(self, request_dict: Dict[str, Any],
                             request_metadata: Dict[str, Any]) \
            -> Generator[Dict[str, Any], None, None]:
        """
        Initiates or continues the agent chat with the session_id
        context in the request.

        :param request_dict: a ChatRequest dictionary
        :param request_metadata: request metadata
        :return: an iterator for (eventually) returned responses dictionaries
        """
        self.request_counter.increment()
        user_text: str = request_dict.get("user_message", {}).get("text", "")
        do_log: bool = "StreamingChat" not in DO_NOT_LOG_REQUESTS

        log_marker = f"'{user_text}'"
        metadata: Dict[str, str] = {
            "request_id": f"server-{uuid.uuid4()}"
        }
        metadata.update(request_metadata)

        if do_log:
            self.request_logger.info(
                metadata,
                "Received a %s request for %s",
                f"{self.agent_name}.StreamingChat", log_marker)

        # Prepare
        factory = ExternalAgentSessionFactory(use_direct=False)
        invocation_context = SessionInvocationContext(factory, self.llm_factory, self.toolbox_factory, metadata)
        invocation_context.start()

        # Set up logging inside async thread
        # Prefer any request_id from the client over what we generated on the server.
        executor: AsyncioExecutor = invocation_context.get_asyncio_executor()
        _ = executor.submit(None, self.server_logging.setup_logging, metadata, metadata.get("request_id"))

        # Delegate to Direct*Session
        agent_network: AgentNetwork = self.agent_network_provider.get_agent_network()
        session: AsyncDirectAgentSession =\
            AsyncDirectAgentSession(
                agent_network=agent_network,
                invocation_context=invocation_context,
                metadata=metadata,
                security_cfg=self.security_cfg)
        # Get our args in order to pass to transport-agnostic session level
        response_dict_generator: Generator[Dict[str, Any], None, None] = session.streaming_chat(request_dict)

        # See if we want to put the request dict in the response
        chat_filter_dict: Dict[str, Any] = {}
        chat_filter_dict = request_dict.get("chat_filter", chat_filter_dict)
        chat_filter_type: str = chat_filter_dict.get("chat_filter_type", "MINIMAL")

        async for response_dict in response_dict_generator:
            # Prepare chat message for output:
            response_dict = ChatMessageConverter().to_dict(response_dict)
            # Do not return the request when the filter is MINIMAL
            if chat_filter_type != "MINIMAL":
                response_dict["request"] = request_dict
            yield response_dict

        request_reporting: Dict[str, Any] = invocation_context.get_request_reporting()
        invocation_context.close()

        # Iterator has finally signaled that there are no more responses to be had.
        # Log that we are done.
        if do_log:
            reporting: str = None
            if request_reporting is not None:
                reporting = json.dumps(request_reporting, indent=4, sort_keys=True)
            self.request_logger.info(metadata, "Request reporting: %s", reporting)
            self.request_logger.info(
                metadata,
                "Done with %s request for %s",
                f"{self.agent_name}.StreamingChat", log_marker)

        self.request_counter.decrement()
