
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
from typing import AsyncGenerator

import contextlib
import json
import uuid

from janus import Queue

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor
from leaf_common.utils.atomic_counter import AtomicCounter

from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.graph.utils.allow_util import AllowUtil
from neuro_san.internals.graph.utils.invocation_util import InvocationUtil
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.run_context.factory.master_toolbox_factory import MasterToolboxFactory
from neuro_san.internals.run_context.factory.master_llm_factory import MasterLlmFactory
from neuro_san.service.generic.service_agent_reservationist import ServiceAgentReservationist
from neuro_san.service.generic.agent_server_logging import AgentServerLogging
from neuro_san.service.generic.chat_message_converter import ChatMessageConverter
from neuro_san.service.interfaces.event_loop_logger import EventLoopLogger
from neuro_san.service.interfaces.server_context_lite import ServerContextLite
from neuro_san.service.usage.usage_logger_factory import UsageLoggerFactory
from neuro_san.service.usage.wrapped_usage_logger import WrappedUsageLogger
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
                 server_logging: AgentServerLogging,
                 server_context: ServerContextLite):
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
        :param server_context: The ServerContext holding global-ish state
        """
        self.request_logger = request_logger
        self.security_cfg = security_cfg
        self.server_logging: AgentServerLogging = server_logging

        # Stuff needed for ServiceAgentReservationist
        self.queues: Queue[AsyncCollatingQueue] = server_context.get_queues()

        self.agent_network_provider: AgentNetworkProvider = agent_network_provider
        self.agent_name: str = agent_name
        self.request_counter = AtomicCounter()
        self.port: int = server_context.get_server_port()

        self.async_executor_pool: AsyncioExecutorPool = server_context.get_executor_pool()
        self.event_work_queue: AsyncCollatingQueue = server_context.get_event_work_queue()

        self.reload_factories()

    def reload_factories(self):
        """
        Reloads the LLM and Toolbox factories from the agent network config.
        This method is called in the constructor,
        and also whenever our underlying agent network and its configuration can change.
        """
        agent_network: AgentNetwork = self.agent_network_provider.get_agent_network()
        config: Dict[str, Any] = agent_network.get_config()
        self.llm_factory: ContextTypeLlmFactory = MasterLlmFactory.create_llm_factory(config)
        self.toolbox_factory: ContextTypeToolboxFactory = MasterToolboxFactory.create_toolbox_factory(config)

        # Load once.
        self.llm_factory.load()
        self.toolbox_factory.load()

    def get_agent_network(self) -> AgentNetwork:
        """
        :return: The agent network for this service
        """
        return self.agent_network_provider.get_agent_network()

    def get_request_count(self) -> int:
        """
        :return: The number of currently active requests
        """
        return self.request_counter.get_count()

    def get_request_timeout_seconds(self) -> float:
        """
        :return: The request timeout in seconds for this service;
        """
        return self.agent_network_provider.get_agent_network().get_request_timeout_seconds()

    def is_mcp_tool(self) -> bool:
        """
        :return: True if the agent served by this service is an MCP tool
        """
        return self.agent_network_provider.get_agent_network().is_mcp_tool()

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
            -> AsyncGenerator[Dict[str, Any], None]:
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

        log_marker: str = self.server_logging.redact_per_env_var(user_text, "AGENT_REQUEST_LOGGING_INPUT_SLICE")
        metadata: Dict[str, str] = {
            "request_id": f"server-{uuid.uuid4()}"
        }
        metadata.update(request_metadata)

        if do_log:
            self.request_logger.info(
                metadata,
                "Received a %s request for %s",
                f"{self.agent_name}.StreamingChat", log_marker)

        # Determine the effective invocation
        agent_network: AgentNetwork = self.agent_network_provider.get_agent_network()
        effective_invocation: str = InvocationUtil.get_effective_invocation(agent_network, request_dict)

        # Create a reservationist for the occasion
        reservationist: Reservationist = None
        if self.queues is not None and AllowUtil.is_allowed(agent_network, "reservations", ["middleware"]):
            reservationist = ServiceAgentReservationist()
            self.queues.sync_q.put(reservationist.get_queue())

        # Prepare
        factory = ExternalAgentSessionFactory(use_direct=False)
        invocation_context = SessionInvocationContext(
            self.agent_name,
            factory,
            self.async_executor_pool,
            self.llm_factory,
            self.toolbox_factory,
            metadata,
            reservationist,
            self.port,
            effective_invocation=effective_invocation,
            event_work_queue=self.event_work_queue)
        invocation_context.start()

        # Set up logging inside async thread
        # Prefer any request_id from the client over what we generated on the server.
        executor: AsyncioExecutor = invocation_context.get_asyncio_executor()
        _ = executor.submit(None, self.server_logging.setup_logging, metadata, metadata.get("request_id"))

        # Delegate to Direct*Session
        session: AsyncDirectAgentSession =\
            AsyncDirectAgentSession(
                agent_network=agent_network,
                invocation_context=invocation_context,
                metadata=metadata,
                security_cfg=self.security_cfg)
        # Get our args in order to pass to transport-agnostic session level
        response_dict_generator: AsyncGenerator[Dict[str, Any], None] = session.streaming_chat(request_dict)

        # See if we want to put the request dict in the response
        extractor = DictionaryExtractor(request_dict)
        chat_filter_type: str = extractor.get("chat_filter.chat_filter_type", "MINIMAL")

        try:
            async for response_dict in response_dict_generator:
                # Prepare chat message for output:
                response_dict = ChatMessageConverter().to_dict(response_dict)
                # Do not return the request when the filter is MINIMAL
                if chat_filter_type != "MINIMAL":
                    response_dict["request"] = request_dict
                yield response_dict
        finally:
            # Put async generator cleanup logic in "finally" part of try-except block;
            # this way we guarantee that underlying response_dict_generator will be closed
            # whether we finish consuming its data stream normally
            # OR we are interrupted downstream
            # and have special "GeneratorExit" exception delivered to us.
            request_reporting: Dict[str, Any] = invocation_context.get_request_reporting()
            # Properly close our async generator:
            if response_dict_generator is not None:
                with contextlib.suppress(Exception):
                    await response_dict_generator.aclose()
            # Ensure that our SessionInvocationContext is always closed,
            # even if generator is interrupted.
            invocation_context.finish_request()
            invocation_context = None

        # Maybe report token accounting to a UsageLogger
        token_dict: Dict[str, Any] = request_reporting.get("token_accounting")
        if token_dict is not None:
            usage_logger: WrappedUsageLogger = UsageLoggerFactory.create_usage_logger()
            await usage_logger.log_usage(token_dict, request_metadata)

        # Iterator has finally signaled that there are no more responses to be had.
        # Log that we are done.
        if do_log:
            reporting: str = None
            if request_reporting is not None:
                reporting = json.dumps(request_reporting, indent=4, sort_keys=False)
            self.request_logger.info(metadata, "Request reporting: %s", reporting)
            self.request_logger.info(
                metadata,
                "Done with %s request for %s",
                f"{self.agent_name}.StreamingChat", log_marker)

        self.request_counter.decrement()

    def should_process_as_event(self, request_dict: Dict[str, Any]) -> bool:
        """
        :return: True if the request should be processed as an event. False otherwise
        """
        agent_network: AgentNetwork = self.agent_network_provider.get_agent_network()
        process_as_event: bool = InvocationUtil.get_effective_invocation(agent_network, request_dict) == "event"
        return process_as_event
