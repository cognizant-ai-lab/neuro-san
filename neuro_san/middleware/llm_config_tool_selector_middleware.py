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
from typing import Optional
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

# Key under which advertised-tools bookkeeping is recorded in sly_data.
# The value is a dictionary keyed by a per-middleware-instance namespace,
# whose values map tool call ids to the list of tool names that were
# advertised to the model on the call that produced them.
#
# This bookkeeping deliberately lives OUTSIDE of langgraph agent state:
# message-rewriting middleware (summarization, PII redaction, etc.) can
# rebuild AIMessages and would silently destroy any bookkeeping carried
# on the messages themselves. sly_data is request-scoped, server-side only,
# and redacted from clients and external tools by default.
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
    call naming a de-selected tool (e.g. a name the model remembered from an earlier turn)
    would otherwise still execute.  To close that gap:

    * awrap_model_call() records, per tool call id, the tool names that were advertised
      to the model on the call that produced it.  The record is kept in sly_data
      (or a private per-instance dictionary when sly_data is not provided), outside
      of langgraph agent state, so other middleware that rewrite messages cannot
      disturb it.
    * awrap_tool_call() rejects any tool call whose name was not among the tools
      advertised on the model call that produced it, returning an error ToolMessage
      instead of executing, so the model can retry.

    Tool calls with no recorded advertisement (e.g. produced by another middleware
    short-circuiting the model call) are allowed through with a warning by default,
    since we cannot know what was advertised for them.  Set unadvertised_policy to
    "deny" to reject such tool calls instead — recommended for agents exposed to
    untrusted input, at the cost of rejecting tool calls fabricated by co-resident
    middleware that bypass the model.

    This middleware does not support dynamic tools: the enforcement records the tool
    list as narrowed at this middleware's layer, so any middleware listed after it
    (composed inside it) that adds or removes tools via request.override(tools=...)
    will make the record diverge from what the model actually saw — added tools get
    falsely denied, removals go unenforced.  If other tool-modifying middleware must
    be combined with this one, list them before this middleware, and do not list any
    tool-modifying middleware after it.

    Only the async hooks are overridden, as neuro-san always drives agents through
    the async path. Synchronous agent invocation raises NotImplementedError from the
    langchain superclass machinery at the first tool call.

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
                origin_str: str = None,
                unadvertised_policy: str = "allow",
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
                        Also used to keep the advertised-tools bookkeeping for execution-time enforcement.
                        When not provided, a private per-instance dictionary is used for that instead.
        :param origin_str: A string representation of where this middleware sits in the agent network.
                        Used to namespace the advertised-tools bookkeeping within the sly_data
                        shared by all agents of the network for the request.
                        When not provided, a per-instance namespace is used.
        :param unadvertised_policy: What to do with a tool call that has no recorded
                        advertisement: "allow" (the default) executes it with a warning,
                        "deny" rejects it with an error ToolMessage.

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

        # Set up after the validations above, so the constructor does not mutate
        # the caller-provided sly_data when it is going to raise.
        self._initialize_enforcement(sly_data, origin_str, unadvertised_policy)

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

    def _initialize_enforcement(self, sly_data: Dict[str, Any], origin_str: str,
                                unadvertised_policy: str) -> None:
        """
        Set up the advertised-tools bookkeeping and policy used for execution-time enforcement.

        :param sly_data: The private sly_data dictionary for the request, shared by all
                        agents of the network.  Can be None, in which case a private
                        per-instance dictionary is used instead.
        :param origin_str: A string namespacing this middleware instance within the shared
                        sly_data.  Can be None, in which case a per-instance namespace
                        is used to avoid tool call id collisions between agents.
        :param unadvertised_policy: "allow" or "deny" for tool calls with no
                        recorded advertisement.
        """
        if unadvertised_policy not in ("allow", "deny"):
            raise ValueError(f"unadvertised_policy must be 'allow' or 'deny', got '{unadvertised_policy}'")
        self.unadvertised_policy: str = unadvertised_policy

        holder: Dict[str, Any] = sly_data if sly_data is not None else {}
        namespace: str = origin_str if origin_str else f"instance-{id(self)}"
        per_request: Dict[str, Dict[Optional[str], List[str]]] = holder.setdefault(ADVERTISED_TOOLS_KEY, {})

        # Maps tool call id -> list of tool names advertised on the model call
        # that produced that tool call. Keys can be None, as providers may omit
        # tool call ids (ToolCall.id is Optional).
        self.advertised_tools: Dict[Optional[str], List[str]] = per_request.setdefault(namespace, {})

    async def awrap_model_call(
                self,
                request: ModelRequest,
                handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
            ) -> Union[ModelResponse, AIMessage]:
        """
        Superclass override which records the advertised tool names for each tool call.

        The superclass narrows request.tools to the selected subset before invoking the
        handler.  We wrap the handler so that whatever tool list actually reached the
        model gets recorded per emitted tool call, for later enforcement in
        awrap_tool_call().

        :param request: The ModelRequest to execute
        :param handler: Async callback that executes the (possibly narrowed) model request
        :return: The model call result
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
        Model-request handler which records the advertised tool names for each tool call.
        Bound with the real handler via functools.partial in awrap_model_call().

        :param handler: Async callback that executes the model request
        :param narrowed_request: The ModelRequest as narrowed by tool selection
        :return: The model call result
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
        denial: Optional[ToolMessage] = self._deny_unadvertised_tool_call(request)
        if denial is not None:
            return denial

        result: Union[ToolMessage, Command] = await handler(request)

        # The tool call is done with its bookkeeping entry, so clean it up to keep
        # the map from growing over long requests and to avoid stale context should
        # a tool call id ever be reused. None ids are kept, as multiple tool calls
        # can share None. The entry is popped only after successful execution so
        # that a retrying outer middleware still finds it.
        call_id: Optional[str] = request.tool_call.get("id")
        if call_id is not None:
            self.advertised_tools.pop(call_id, None)

        return result

    def _stamp_advertised_tools(self, narrowed_request: ModelRequest, response: Any) -> None:
        """
        Record, per tool call the model emitted, the tool names that were advertised
        to the model on the call that produced it.

        :param narrowed_request: The ModelRequest that was actually executed,
                                 whose tools list is the advertised (selected) tool set.
        :param response: The ModelResponse (or bare AIMessage) returned by the handler.
        """
        advertised: List[str] = []
        for tool in narrowed_request.tools:
            if isinstance(tool, dict):
                # Provider-specific tool dicts may or may not carry a name
                name: Optional[str] = tool.get("name")
            else:
                name = tool.name
            if name is not None:
                advertised.append(name)

        messages: List[Any] = getattr(response, "result", None)
        if messages is None:
            messages = [response]

        for message in messages:
            if not isinstance(message, AIMessage):
                continue
            for tool_call in message.tool_calls or []:
                self.advertised_tools[tool_call.get("id")] = advertised

    def _deny_unadvertised_tool_call(self, request: ToolCallRequest) -> Optional[ToolMessage]:
        """
        Determine whether a tool call should be denied because its tool was not
        advertised to the model on the call that produced it.

        Tool calls with no recorded advertisement are allowed through: they were
        produced outside this middleware's model wrapping (e.g. another middleware
        short-circuiting the model call), and we cannot know what was advertised
        for them.

        :param request: The ToolCallRequest describing the tool call to execute
        :return: An error ToolMessage if the call should be denied, or None to allow it.
        """
        tool_name: Optional[str] = request.tool_call.get("name")
        call_id: Optional[str] = request.tool_call.get("id")

        advertised: Optional[List[str]] = self.advertised_tools.get(call_id)
        if advertised is None:
            # No recorded advertisement for this tool call. See docstring above.
            if self.unadvertised_policy == "allow":
                self.logger.warning("Tool call for %s has no recorded advertised tools. Allowing.", tool_name)
                return None
            self.logger.warning("Tool call for %s has no recorded advertised tools. Denying per policy.", tool_name)
            return self._make_denial(
                tool_name, call_id,
                f"Error: the tool call for '{tool_name}' has no recorded tool selection "
                "and was not executed.")

        if tool_name in advertised:
            return None

        self.logger.warning("Denying tool call for %s: not among advertised tools %s", tool_name, advertised)
        return self._make_denial(
            tool_name, call_id,
            f"Error: tool '{tool_name}' was not among the tools selected for this request "
            f"and was not executed. Try one of [{', '.join(advertised)}].")

    @staticmethod
    def _make_denial(tool_name: Optional[str], call_id: Optional[str], content: str) -> ToolMessage:
        """
        Construct the error ToolMessage for a denied tool call.

        :param tool_name: The name of the tool whose call is being denied.
        :param call_id: The id of the tool call being denied. Can be None.
        :param content: The error message content for the model to read.
        :return: A ToolMessage carrying the denial.
        """
        return ToolMessage(
            content=content,
            # ToolMessage requires a string tool_call_id, but providers may omit ids
            # from tool calls (ToolCall.id is Optional).
            tool_call_id=call_id if call_id is not None else "unknown",
            name=tool_name,
            status="error",
        )
