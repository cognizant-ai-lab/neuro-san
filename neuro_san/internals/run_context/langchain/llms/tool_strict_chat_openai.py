
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
from typing import Callable
from typing import Dict
from typing import Optional
from typing import Sequence
from typing import Type
from typing import Union

from typing_extensions import override

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_openai.chat_models.base import ChatOpenAI


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
        Chat Completions, where OpenAI requires strict function tools next to it.

        :param tools: The tool definitions to bind
        :param tool_choice: Which tool the model must call, as ChatOpenAI.bind_tools() takes it
        :param strict: The strict value for every tool; None means use tool_strict
        :param parallel_tool_calls: Whether the model may call several tools at once
        :param response_format: An optional schema for a structured answer
        :param kwargs: Any other keyword arguments ChatOpenAI.bind_tools() accepts
        :return: The chat model with the tools bound
        """
        # langchain forces strict=True for a response_format on Chat Completions only; the Responses
        # API has no such rule, so the default still applies there.
        langchain_decides: bool = bool(response_format) and not self.use_responses_api
        use_default: bool = strict is None and not langchain_decides
        effective_strict: Optional[bool] = self.tool_strict if use_default else strict
        return super().bind_tools(tools,
                                  tool_choice=tool_choice,
                                  strict=effective_strict,
                                  parallel_tool_calls=parallel_tool_calls,
                                  response_format=response_format,
                                  **kwargs)
