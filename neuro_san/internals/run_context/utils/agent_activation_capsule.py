
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
from __future__ import annotations

from logging import getLogger
from logging import Logger
from traceback import format_exc
from typing import Any
from typing import Dict
from typing import List

from typing_extensions import override

from aiohttp.client_exceptions import ClientConnectionError

from langchain_core.messages.base import BaseMessage

from leaf_common.logging.sensitive_logger import SensitiveLogger

from neuro_san.interfaces.activation_capsule import ActivationCapsule
from neuro_san.interfaces.async_agent_session import AsyncAgentSession
from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.callable_activation import CallableActivation
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.interfaces.lingering_resource import LingeringResource
from neuro_san.internals.run_context.interfaces.llm_resources import LlmResources
from neuro_san.internals.run_context.interfaces.run_context import RunContext
from neuro_san.internals.utils.external_agent_parsing import ExternalAgentParsing
from neuro_san.message.utils.content_utils import ContentUtils


class AgentActivationCapsule(ActivationCapsule, LingeringResource):
    """
    A helper class that encapsulates bits needed for creating agent Activations,
    LLM model instances and other neuro-san-y resources.
    """

    def __init__(self, parent_run_context: RunContext,
                 parent_agent_spec: Dict[str, Any] = None,
                 agent_tool_factory: AgentToolFactory = None):
        """
        :param parent_run_context: The RunContext of the agent calling this method
        :param parent_agent_spec: The spec of the agent calling this method.
        :param agent_tool_factory: A factory that will be used to create the agent tool
        """
        self.parent_run_context: RunContext = parent_run_context
        self.parent_agent_spec: Dict[str, Any] = parent_agent_spec
        self.factory: AgentToolFactory = agent_tool_factory
        self.lingerers: List[LingeringResource] = []
        self.sessions: List[AsyncAgentSession] = []
        # Exception messages and tracebacks can carry sensitive request data,
        # so route them through a SensitiveLogger, which respects the
        # LEAF_LOG_SENSITIVE env var setting.
        logger: Logger = getLogger(self.__class__.__name__)
        self.sensitive_logger: SensitiveLogger = SensitiveLogger(logger)

    async def close_of_request(self, parent_resource: LingeringResource = None):
        """
        Release resources owned by this context when the request is complete.
        This can happen earlier than when the work is complete.

        :param parent_resource: parent resource, if any
        """
        # Do nothing by default for easier implementation inheritance

    async def close_of_work(self, parent_resource: LingeringResource = None):
        """
        Release resources owned by this context when the work is all done.
        This can happen later than when the request is complete.

        :param parent_resource: parent resource, if any
        """
        # Swap out the list first so a second call does not close anything twice,
        # and so resources added while closing are not lost.
        lingerers: List[LingeringResource] = self.lingerers
        self.lingerers = []

        # Close every lingerer, even when an earlier one fails.
        lingering_resource: LingeringResource = None
        for lingering_resource in lingerers:
            try:
                await lingering_resource.close_of_work(self)
            except Exception as exception:  # pylint: disable=broad-exception-caught
                # Broad on purpose: one failed close must not leave the remaining resources open.
                self.sensitive_logger.error("Failed to close %s: %s\n%s",
                                            lingering_resource.__class__.__name__, str(exception),
                                            format_exc())

        # Same swap as above for the sessions handed out by create_session().
        sessions: List[AsyncAgentSession] = self.sessions
        self.sessions = []

        # Close every session, even when an earlier one fails.
        session: AsyncAgentSession = None
        for session in sessions:
            try:
                session.close()
            except Exception as exception:  # pylint: disable=broad-exception-caught
                # Broad on purpose: one failed close must not leave the remaining sessions open.
                self.sensitive_logger.error("Failed to close %s: %s\n%s",
                                            session.__class__.__name__, str(exception),
                                            format_exc())

    @override
    async def use_tool(self, tool_name: str, tool_args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Calls a tool or agent by name.

        NOTE: This method is not correctly reporting history or anything like that just yet.

        :param tool_name: The name of the tool to invoke
        :param tool_args: A dictionary of arguments to send to the tool.
        :param sly_data: private data dictionary to send to the tool.
        :return: A string representing the last received content text of the last message.
        """

        if self.factory is None or self.parent_agent_spec is None:
            raise ValueError(
                "AgentActivationCapsule.use_tool() requires an AgentToolFactory and parent_agent_spec; "
                "this capsule was created without them."
            )

        invocation_context: InvocationContext = self.parent_run_context.get_invocation_context()
        invocation: str = invocation_context.get_effective_invocation()
        callable_activation: CallableActivation = self.factory.create_agent_activation(
                                                    self.parent_run_context, self.parent_agent_spec,
                                                    tool_name, sly_data, tool_args,
                                                    self.factory, invocation)

        message: BaseMessage = None
        try:
            message = await callable_activation.build()

        except ClientConnectionError as exception:
            # There is a case where we could give a little more help.
            invocation_context: InvocationContext = self.parent_run_context.get_invocation_context()
            async_factory: AsyncAgentSessionFactory = invocation_context.get_async_session_factory()
            if not async_factory.is_use_direct() and tool_name.startswith("/"):
                # Special case where we can give a hint about using direct
                raise ValueError(f"""
Attempt to call {tool_name} as an external agent network over http failed.
If you are getting this from the agent_cli command line, consider adding the --local_externals_direct
flag to your invocation.
""") from exception

            # Nope. Just a regular http connection failure given the tool_name. Can't help ya.
            raise exception

        finally:
            # Release the sub-agent's resources (LLM clients, sockets) as soon as
            # its call is done rather than lingering until close_of_work().
            # A CodedTool that calls agents in a loop would otherwise hold
            # every sub-agent's LLM client until the CodedTool itself returns.
            try:
                await callable_activation.close_of_work(self.parent_run_context)
            except Exception as exception:  # pylint: disable=broad-exception-caught
                # Cleanup failures must not replace the tool's result or exception.
                self.sensitive_logger.error("Failed to close %s: %s\n%s",
                                            callable_activation.__class__.__name__, str(exception),
                                            format_exc())

        # We got a message back. This method's contract is a str. Today the
        # sub-agent's final message always carries str content (its chain
        # output is flattened before it is journaled), so this projection is
        # an identity. Once native block content is preserved through that
        # message (later rungs of issue #1222), it keeps the contract: callers
        # hand this value straight to the calling LLM (copyist.py f-strings it
        # into the tool result) and would otherwise see a Python repr of the
        # block list.
        return ContentUtils.flatten_to_text(message)

    @override
    async def use_reservation(self, reservation: Reservation, args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Calls a reserved temporary agent network.
        For now this assumes a local copy and delegates to use_tool() with "/<reservation_id>".

        NOTE: This method is not correctly reporting history or anything like that just yet.

        :param reservation: The Reservation to invoke
        :param args: A dictionary of arguments to send to the reserved temporary network.
        :param sly_data: private data dictionary to send to the reserved temporary network.
        :return: A string representing the last received content text of the last message.
        """
        # DEF - for now just assume a local copy
        reservation_id: str = reservation.get_reservation_id()
        result: str = await self.use_tool(f"/{reservation_id}", args, sly_data)
        return result

    @override
    def create_chat_model(self, llm_config: Dict[str, Any], sly_data: Dict[str, Any], num_fallbacks: int = None) -> Any:
        """
        Creates an LLM model instance.
        The model's resources are released in close_of_work().

        :param llm_config: The llm config dictionary
        :param sly_data: The private sly_data dictionary. This is needed for bring-your-own-key scenarios.
        :param num_fallbacks: The number of fallbacks to try. Default value of None implies all.
        :return: The llm model to use given the context type (usually langchain)
        :raises ValueError: If the LLM cannot be created from the llm_config and sly_data.
        """

        invocation_context: InvocationContext = self.parent_run_context.get_invocation_context()
        llm_factory: ContextTypeLlmFactory = invocation_context.get_llm_factory()

        llm_resources: Any = llm_factory.create_llm_with_fallbacks(llm_config, sly_data, num_fallbacks)
        if llm_resources is None:
            raise ValueError("Unable to create LLM from llm_config (missing required configuration and/or sly_data).")
        if isinstance(llm_resources, dict):
            llm_resources_dict: Dict[str, Any] = llm_resources
            # For now, do not worry about the "construction_errors" or "api_key_errors" keys.
            # These are very likely to already be handled by the front man.
            required_sly_data: List[str] = llm_resources_dict.get("required_sly_data_errors", [])
            required: str = "\n".join(sorted(required_sly_data))
            raise ValueError(
                "LLM operation for this agent requires at least one of the following set in sly_data.llm_config:\n"
                f"{required}\n"
            )

        typed_llm_resources: LlmResources = llm_resources
        self.lingerers.append(typed_llm_resources)

        model: Any = typed_llm_resources.get_model()

        return model

    @override
    async def create_session(self, agent_name: str) -> AsyncAgentSession:
        """
        Creates an AsyncAgentSession for an external agent network
        through the invocation context's session factory.

        Note: Use use_tool() to invoke agents either internal or external to the graph.

        The session provided here is to be used for agent metadata such as function() and connectivity().
        Chatting through its streaming_chat() skips the framework's policies that use_tool() applies,
        especially those surrounding sly_data and message journaling.

        The session is owned by the capsule and closed in close_of_work(),
        so callers do not need to close it.

        :param agent_name: A reference to an external agent network, either
                    "/<agent_name>" for an agent network on the same server
                    or a full url, as it would appear in an agent spec's tools list.
        :return: An AsyncAgentSession for the agent network
        :raises ValueError: If agent_name is not an external agent reference,
                    or no session can be created for it.
        """
        # The session factory only knows about external agents,
        # so catch a bare in-network name here with a clear message.
        if not ExternalAgentParsing.is_external_agent(agent_name):
            raise ValueError(
                f"AgentActivationCapsule.create_session() requires an external agent reference "
                f"such as \"/{agent_name}\" or a full url; got \"{agent_name}\"."
            )

        invocation_context: InvocationContext = self.parent_run_context.get_invocation_context()
        invocation: str = invocation_context.get_effective_invocation()
        async_factory: AsyncAgentSessionFactory = invocation_context.get_async_session_factory()
        session: AsyncAgentSession = await async_factory.async_create_session(agent_name, invocation_context,
                                                                              invocation)
        if session is None:
            raise ValueError(f"Unable to create a session for external agent {agent_name}.")

        self.sessions.append(session)
        return session
