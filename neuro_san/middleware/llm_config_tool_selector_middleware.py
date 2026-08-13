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
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import List
from typing import Union

from functools import partial
from logging import getLogger
from logging import Logger

from langchain.agents.middleware import LLMToolSelectorMiddleware
from langchain.agents.middleware.tool_selection import DEFAULT_SYSTEM_PROMPT
from langchain.agents.middleware.types import ModelRequest
from langchain.agents.middleware.types import ModelResponse
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import ToolMessage
from langchain_core.runnables.base import RunnableSerializable
from langchain_core.runnables.fallbacks import RunnableWithFallbacks
from langgraph.types import Command

from neuro_san.internals.run_context.utils.activation_capsule import ActivationCapsule

# Key under which the list of tool names advertised to the model is recorded
# on each AIMessage's response_metadata. The stamp travels with the message
# through agent state and checkpoints, so tool calls can be validated against
# the exact tool set that was advertised on the model call that produced them.
ADVERTISED_TOOLS_KEY: str = "neuro_san_advertised_tools"


class LlmConfigToolSelectorMiddleware(LLMToolSelectorMiddleware):
    """
    LLMToolSelectorMiddleware implementation that understands neuro-san LLM Configs.

    This can significantly reduce token and time costs for agent trees that were deep
    and which can be flattened. But note that these improvements come at a cost of flexibility
    in federation and less complete answers.  Completeness in answers will depend much more on
    the descriptions of the leaf agents.

    Unlike the langchain superclass, this middleware also enforces the selection at
    tool-execution time.  The superclass only narrows the tool list *advertised* to the
    model per call; the agent executor is still built with the full tool list, so a tool
    call naming a de-selected tool (e.g. a name the model remembered from an earlier turn,
    or replayed from checkpointed state) would otherwise still execute.  To close that gap:

    * awrap_model_call() stamps the advertised tool names onto each AIMessage the
      model produces (in response_metadata).
    * awrap_tool_call() rejects any tool call whose name was not among the tools
      advertised on the model call that produced it, returning an error ToolMessage
      instead of executing, so the model can retry.

    Only the async hooks are overridden, as neuro-san always drives agents through
    the async path. Synchronous agent invocation would bypass this enforcement.

    Note that LLM-based tool selection remains a token/latency optimization, not a
    security boundary: the selection model chooses tools based on the (untrusted) last
    user message, so it can be steered toward any configured tool.  The set of tools
    configured for the agent is the actual capability boundary.
    """

    # pylint: disable=too-many-arguments
    def __init__(
                self,
                *,
                activation_capsule: ActivationCapsule,
                llm_config: Dict[str, Any],
                sly_data: Dict[str, Any] = None,
                system_prompt: str = DEFAULT_SYSTEM_PROMPT,
                max_tools: int | None = None,
                always_include: List[str] | None = None,
            ) -> None:
        """
        Constructor

        :param activation_capsule: A helper class that encapsulates bits needed for creating model instances
                                   from a given LLM Config.
        :param llm_config: The LLM Config to use to create model instances.
        :param sly_data: A dictionary of private data that can be passed to the model factory creating the LLMs.
                        Not strictly necessary for all cases, but definitely needed for bring-your-own-key scenarios.

        ... the rest of the args come from the langchain superclass.

        :param system_prompt: The system prompt to use for selecting the tools to use.
        :param max_tools: The maximum number of tools to use.  Defaults to None, implying no limit,
                            but practically speaking most tool-using LLMs have a limit of 7-10.
        :param always_include: A list of tool names to always include. These are not subject to the max_tools limit,
                            and if you include any, you should also further limit max_tools.
        """

        self.logger: Logger = getLogger(self.__class__.__name__)

        if activation_capsule is None:
            raise ValueError("activation_capsule is required")

        if llm_config is None:
            raise ValueError("llm_config is required")

        my_model: RunnableSerializable = activation_capsule.create_chat_model(llm_config, sly_data)

        # The basis for this class is the langchain implementation of LLMToolSelectorMiddleware
        # and it does not take Runnables as args, but it really does seem to function with
        # fallbacks, so we do some trickery.

        # The langchain superclass expects a BaseChatModel instance
        init_model: BaseChatModel = None
        if isinstance(my_model, BaseChatModel):
            init_model = my_model
        elif isinstance(my_model, RunnableWithFallbacks):
            # If we have a RunnableWithFallbacks, we need to get the underlying first model for init
            init_model = my_model.runnable

        # Go through superclass init
        super().__init__(model=init_model, system_prompt=system_prompt, max_tools=max_tools,
                         always_include=always_include)

        # Now subvert the superclass model with our RunnableWithFallbacks.
        self.model = my_model

    async def awrap_model_call(
                self,
                request: ModelRequest,
                handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
            ) -> Union[ModelResponse, AIMessage]:
        """
        Superclass override which stamps the advertised tool names onto the model output.

        The superclass narrows request.tools to the selected subset before invoking the
        handler.  We wrap the handler so that whatever tool list actually reached the
        model gets recorded on the resulting AIMessage(s), for later enforcement in
        awrap_tool_call().

        :param request: The ModelRequest to execute
        :param handler: Async callback that executes the (possibly narrowed) model request
        :return: The model call result, with advertised tool names stamped on it
        """
        stamping_handler: Callable[[ModelRequest], Awaitable[ModelResponse]] = \
            partial(self._astamping_handler, handler)
        return await super().awrap_model_call(request, stamping_handler)

    async def _astamping_handler(
                self,
                handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
                narrowed_request: ModelRequest,
            ) -> ModelResponse:
        """
        Model-request handler which stamps advertised tool names onto the model output.
        Bound with the real handler via functools.partial in awrap_model_call().

        :param handler: Async callback that executes the model request
        :param narrowed_request: The ModelRequest as narrowed by tool selection
        :return: The model call result, with advertised tool names stamped on it
        """
        response: ModelResponse = await handler(narrowed_request)
        self._stamp_advertised_tools(narrowed_request, response)
        return response

    async def awrap_tool_call(
                self,
                request: ToolCallRequest,
                handler: Callable[[ToolCallRequest], Awaitable[Union[ToolMessage, Command]]],
            ) -> Union[ToolMessage, Command]:
        """
        Enforce the tool selection at execution time.

        Rejects any tool call whose name was not among the tools advertised on the
        model call that produced it, returning an error ToolMessage instead of
        executing the tool, so the model can retry.

        :param request: The ToolCallRequest describing the tool call to execute
        :param handler: Async callback that actually executes the tool call
        :return: The ToolMessage or Command resulting from the tool call,
                 or an error ToolMessage if the tool was not advertised.
        """
        denial: ToolMessage = self._deny_unadvertised_tool_call(request)
        if denial is not None:
            return denial
        return await handler(request)

    def _stamp_advertised_tools(self, narrowed_request: ModelRequest, response: Any) -> None:
        """
        Record the tool names advertised to the model on each AIMessage it produced.

        :param narrowed_request: The ModelRequest that was actually executed,
                                 whose tools list is the advertised (selected) tool set.
        :param response: The ModelResponse (or bare AIMessage) returned by the handler.
        """
        advertised: List[str] = []
        for tool in narrowed_request.tools:
            if isinstance(tool, dict):
                # Provider-specific tool dicts may or may not carry a name
                name: str = tool.get("name")
            else:
                name = tool.name
            if name is not None:
                advertised.append(name)

        messages: List[Any] = getattr(response, "result", None)
        if messages is None:
            messages = [response]

        for message in messages:
            if isinstance(message, AIMessage):
                message.response_metadata[ADVERTISED_TOOLS_KEY] = advertised

    def _deny_unadvertised_tool_call(self, request: ToolCallRequest) -> ToolMessage:
        """
        Determine whether a tool call should be denied because its tool was not
        advertised to the model on the call that produced it.

        Tool calls whose originating AIMessage carries no advertised-tools stamp are
        allowed through: they were produced outside this middleware's model wrapping
        (e.g. chat history checkpointed before this enforcement existed, or another
        middleware short-circuiting the model call), and we cannot know what was
        advertised for them.

        :param request: The ToolCallRequest describing the tool call to execute
        :return: An error ToolMessage if the call should be denied, or None to allow it.
        """
        tool_name: str = request.tool_call.get("name")

        origin: AIMessage = self._find_origin_message(request)
        if origin is None:
            self.logger.warning("Could not attribute tool call for %s to an AIMessage. Allowing.", tool_name)
            return None

        advertised: List[str] = origin.response_metadata.get(ADVERTISED_TOOLS_KEY)
        if advertised is None:
            # Unstamped message. See docstring above.
            self.logger.warning("Tool call for %s came from an unstamped AIMessage. Allowing.", tool_name)
            return None

        if tool_name in advertised:
            return None

        self.logger.warning("Denying tool call for %s: not among advertised tools %s", tool_name, advertised)
        return ToolMessage(
            content=f"Error: tool '{tool_name}' was not among the tools selected for this request "
                    "and was not executed. Use one of the available tools instead.",
            tool_call_id=request.tool_call.get("id"),
            name=tool_name,
            status="error",
        )

    @staticmethod
    def _find_origin_message(request: ToolCallRequest) -> AIMessage:
        """
        Find the AIMessage in agent state that produced the given tool call.

        :param request: The ToolCallRequest describing the tool call to execute
        :return: The AIMessage that emitted this tool call, matched by tool call id
                 when available, otherwise the most recent AIMessage bearing tool calls.
                 Returns None if no candidate is found.
        """
        state: Any = request.state
        if isinstance(state, dict):
            messages: List[Any] = state.get("messages", [])
        else:
            messages = getattr(state, "messages", [])

        call_id: str = request.tool_call.get("id")

        fallback: AIMessage = None
        for message in reversed(messages):
            if not isinstance(message, AIMessage) or not message.tool_calls:
                continue
            if fallback is None:
                fallback = message
            if call_id is not None:
                for tool_call in message.tool_calls:
                    if tool_call.get("id") == call_id:
                        return message

        return fallback
