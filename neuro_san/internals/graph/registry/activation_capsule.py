
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

from typing import Any
from typing import Dict
from typing import List

from aiohttp.client_exceptions import ClientConnectionError

from langchain_core.messages.base import BaseMessage

from neuro_san.internals.graph.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.graph.interfaces.callable_activation import CallableActivation
from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.interfaces.lingering_resource import LingeringResource
from neuro_san.internals.run_context.interfaces.run_context import RunContext


class ActivationCapsule(LingeringResource):
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

    async def close_of_work(self, parent_resource: LingeringResource = None):
        """
        Release resources owned by this context when the work is all done.
        This can happen later than when the request is complete.

        :param parent_resource: parent resource, if any
        """
        for lingering_resource in self.lingerers:
            await lingering_resource.close_of_work(self)

    async def use_tool(self, tool_name: str, tool_args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Experimental method to call a tool more directly from a subclass.

        NOTE: This method is not correctly reporting history or anything like that just yet.

        :param tool_name: The name of the tool to invoke
        :param tool_args: A dictionary of arguments to send to the tool.
        :param sly_data: private data dictionary to send to the tool.
        :return: A string representing the last received content text of the last message.
        """

        if self.factory is None or self.parent_agent_spec is None:
            raise ValueError(
                "ActivationCapsule.use_tool() requires an AgentToolFactory and parent_agent_spec; "
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

        # We got a message back, take the content as the return string
        return message.content

    def create_chat_model(self, llm_config: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        """
        :param llm_config: The llm config dictionary
        :param sly_data: The private sly_data dictionary. This is needed for bring-your-own-key scenarios.
        :return: The llm model to use given the context type (usually langchain)
        """

        invocation_context: InvocationContext = self.parent_run_context.get_invocation_context()
        llm_factory: ContextTypeLlmFactory = invocation_context.get_llm_factory()

        llm_resources = llm_factory.create_llm(llm_config, sly_data)
        if llm_resources is None:
            raise ValueError("Unable to create LLM from llm_config (missing required configuration and/or sly_data).")
        if isinstance(llm_resources, set):
            required = "\n".join(sorted(llm_resources))
            raise ValueError(
                "LLM operation for this agent requires at least one of the following set in sly_data.llm_config:\n"
                f"{required}\n"
            )

        self.lingerers.append(llm_resources)

        model: Any = llm_resources.get_model()

        return model
