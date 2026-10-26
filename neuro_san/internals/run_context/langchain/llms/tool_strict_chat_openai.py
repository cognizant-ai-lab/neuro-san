
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
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Type
from typing import Union

from typing_extensions import override

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_function
from langchain_openai.chat_models.base import ChatOpenAI

from neuro_san.internals.run_context.langchain.llms.translate_options import TranslateOptions


# ChatOpenAI already sits deep in langchain's class tree; one more level is unavoidable here.
# pylint: disable=too-many-ancestors
class ToolStrictChatOpenAI(ChatOpenAI):
    """
    ChatOpenAI with a configurable default for the strict flag of function tools.

    OpenAI's two endpoints treat a tool without a strict value differently. Chat Completions
    binds it non-strict. The Responses API tries strict mode, in which the model has to fill
    in every property of the tool's schema, optional ones included. Tools whose optional
    arguments depend on each other, such as those of many MCP servers, then get calls the
    server rejects.

    langchain writes strict into each tool inside bind_tools(), and create_agent() calls that
    method without a strict value for ordinary tool binding, so a default on the chat model is
    the simplest place to set it. tool_strict is the llm_config value: False sends "strict": false
    on every tool, True sends "strict": true, None sends nothing and lets each endpoint apply its
    own default.

    Tools reach bind_tools() in two shapes. Coded tools, MCP tools and agent tools arrive as
    langchain BaseTools, which langchain converts to OpenAI format and stamps with the value
    itself. The llm_config's provider_tools arrive as raw dicts, which langchain passes through
    unchanged, so a function definition among them gets the value written in here; the built-in
    tools among them need no flag and go through untouched.
    """

    # The default strict value for bind_tools(). Set from the "tool_strict" key of the llm_config.
    tool_strict: Optional[bool] = None

    # The signature mirrors ChatOpenAI.bind_tools() so that every caller argument keeps its name.
    # The Runnable return annotation is load-bearing: RunnableWithFallbacks forwards a method to
    # the fallback models only when its return type is a Runnable.
    # pylint: disable=too-many-arguments
    @override
    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type, Callable, BaseTool]],
        *,
        tool_choice: Optional[Union[Dict[str, Any], str, bool]] = None,
        strict: Optional[bool] = None,
        parallel_tool_calls: Optional[bool] = None,
        response_format: Optional[Any] = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """
        Binds tools to the chat model, filling in tool_strict when the caller gives no strict value.

        The default steps aside only where langchain sets strict itself: for a response_format on
        Chat Completions, where OpenAI requires strict function tools next to it. A function
        definition already in OpenAI tool format gets the value too, unless it names its own
        strict; built-in tool dicts pass through.

        :param tools: The tool definitions to bind
        :param tool_choice: Which tool the model must call, as ChatOpenAI.bind_tools() takes it
        :param strict: The strict value for every tool; None means use tool_strict
        :param parallel_tool_calls: Whether the model may call several tools at once
        :param response_format: An optional schema for a structured answer
        :param kwargs: Any other keyword arguments ChatOpenAI.bind_tools() accepts
        :return: The chat model with the tools bound
        """
        # langchain forces strict=True for a response_format on Chat Completions only; the Responses
        # API has no such rule, so the default still applies there. langchain keys that rule on the
        # configured use_responses_api value, not on the endpoint it infers for a null value, so null
        # counts as Chat Completions here as well and the two rules never disagree.
        langchain_decides: bool = bool(response_format) and not self.use_responses_api
        use_default: bool = strict is None and not langchain_decides
        effective_strict: Optional[bool] = self.tool_strict if use_default else strict
        # Preformatted definitions get the value langchain ends up writing into the tools it converts:
        # True where its response_format rule fires (unless the caller said False), else the value above.
        forced_strict: bool = langchain_decides and effective_strict is not False
        written_strict: Optional[bool] = True if forced_strict else effective_strict
        strict_tools: List[Any] = self.with_strict_on_preformatted(tools, written_strict)
        runnable: Runnable[LanguageModelInput, AIMessage] = super().bind_tools(
            strict_tools,
            tool_choice=tool_choice,
            strict=effective_strict,
            parallel_tool_calls=parallel_tool_calls,
            response_format=response_format,
            **kwargs
        )
        return runnable

    @staticmethod
    def with_strict_on_preformatted(tools: Sequence[Any], strict: Optional[bool]) -> List[Any]:
        """
        Writes the strict value into function definitions that are already in OpenAI tool format,
        such as entries of the llm_config's provider_tools, and name no strict of their own, since
        langchain passes those through unchanged.

        Only dicts are candidates. Every other kind of tool comes back untouched, since langchain
        converts those itself and writes the value in as it does so.

        :param tools: The tool definitions handed to bind_tools()
        :param strict: The strict value to write, or None to leave every definition alone
        :return: The tool definitions, with the value written in where it was missing
        """
        if strict is None:
            return list(tools)
        updated: List[Any] = []
        for tool in tools:
            if isinstance(tool, dict):
                updated.append(ToolStrictChatOpenAI.with_strict_on_one(tool, strict))
            else:
                updated.append(tool)
        return updated

    @staticmethod
    def with_strict_on_one(tool: Dict[str, Any], strict: bool) -> Dict[str, Any]:
        """
        Writes the strict value into one tool dict, if it is a function definition that names none.

        Both shapes OpenAI accepts are handled: Chat Completions' {"type": "function", "function": {...}}
        and the Responses API's flat {"type": "function", "name": ...}. langchain's converter writes the
        value and, for True, rewrites the schema the way strict mode needs. Built-in tool dicts such as
        web_search come back untouched.

        :param tool: One tool definition in dict form
        :param strict: The strict value to write
        :return: A copy of the definition with the value written in, or the definition as given
        """
        if tool.get("type") != "function":
            return tool
        function: Any = tool.get("function")
        if isinstance(function, dict):
            if "strict" in function:
                return tool
            nested: Dict[str, Any] = dict(tool)
            nested["function"] = convert_to_openai_function(function, strict=strict)
            return nested
        if "name" in tool and "strict" not in tool:
            # The converter returns only the function keys (name, description, parameters, strict).
            # They are written over a copy of the definition, which keeps the type and any other keys.
            converted: Dict[str, Any] = convert_to_openai_function(tool, strict=strict)
            flat: Dict[str, Any] = dict(tool)
            flat.update(converted)
            return flat
        return tool

    #
    # Below here are static items used stricture only for TypeScript translation.
    #

    @staticmethod
    def kwargs_constructor(kwargs: Dict[str, Any]) -> ToolStrictChatOpenAI:
        """
        Constructs a ToolStrictChatOpenAI from the keyword arguments dictionary.

        :param kwargs: The keyword arguments to pass to the constructor
        :return: A ToolStrictChatOpenAI
        """
        translate_options: TranslateOptions = TranslateOptions()
        translated: Dict[str, Any] = translate_options(kwargs)
        instance: ToolStrictChatOpenAI = ToolStrictChatOpenAI(**translated)
        return instance
