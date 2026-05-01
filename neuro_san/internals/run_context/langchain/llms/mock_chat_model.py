
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

"""
A mock chat model for load testing neuro-san without incurring LLM token costs.

Supports tool calling so that full agent network traversal is exercised.
Responses are drawn from a configurable set of predefined texts.
Random latency is added to emulate real LLM behavior.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid

from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional
from typing import Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import BaseMessage
from langchain_core.messages import ToolMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool


# Default canned responses used when no custom responses are provided.
DEFAULT_RESPONSES: List[str] = [
    "Based on my analysis, the answer to your question is 42.",
    "I have reviewed the available information and here is my assessment: "
    "everything looks good and is proceeding as expected.",
    "After careful consideration, I recommend proceeding with the proposed approach. "
    "The benefits outweigh the potential risks.",
    "Here is a summary of the key findings: the data indicates positive trends "
    "across all measured dimensions.",
    "Thank you for your question. The short answer is yes, and here are the details "
    "to support that conclusion.",
    "I have completed the requested task. All items have been processed successfully "
    "and the results are ready for your review.",
    "The analysis is complete. Three main factors contribute to the observed outcome: "
    "timing, resource allocation, and coordination.",
    "Based on the information provided, I suggest the following course of action: "
    "prioritize the critical items first, then address the remaining tasks in order.",
]


def _default_value_for_schema(schema: Dict[str, Any]) -> Any:
    """
    Generate a minimal default value that satisfies a JSON Schema type.
    """
    schema_type = schema.get("type", "string")
    if schema_type == "string":
        enum = schema.get("enum")
        if enum:
            return enum[0]
        return "test"
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return True
    if schema_type == "array":
        return []
    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        obj = {}
        for prop_name in required:
            prop_schema = properties.get(prop_name, {"type": "string"})
            obj[prop_name] = _default_value_for_schema(prop_schema)
        return obj
    return "test"


def _generate_tool_args(tool_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate minimal arguments that satisfy a tool's parameter schema.

    :param tool_schema: The OpenAI-style function schema for the tool.
    :return: A dictionary of argument name -> default value for all required params.
    """
    parameters = tool_schema.get("parameters", {})
    properties = parameters.get("properties", {})
    required = parameters.get("required", list(properties.keys()))
    args = {}
    for param_name in required:
        param_schema = properties.get(param_name, {"type": "string"})
        args[param_name] = _default_value_for_schema(param_schema)
    return args


class MockChatModel(BaseChatModel):
    """
    A mock LangChain chat model for load testing.

    Features:
    - Returns responses from a configurable list of predefined texts
    - Adds random latency to simulate real LLM response times
    - Supports tool calling so full agent-network traversal is exercised
    - Supports streaming

    When tools are bound and the incoming messages do not already contain
    tool results, the model picks a random tool and generates a tool call
    with minimal valid arguments.  When tool results are already present
    (i.e. the agent loop is returning from a sub-agent), the model returns
    a plain text response to complete the turn.
    """

    responses: Optional[List[str]] = None
    """List of canned responses to cycle through."""

    min_latency: float = 0.1
    """Minimum simulated latency in seconds."""

    max_latency: float = 1.5
    """Maximum simulated latency in seconds."""

    i: int = 0
    """Internal index for cycling through responses."""

    @property
    def _llm_type(self) -> str:
        return "mock-chat-model"

    def _get_responses(self) -> List[str]:
        if self.responses:
            return self.responses
        return DEFAULT_RESPONSES

    def _next_response(self) -> str:
        """Return the next canned response, cycling through the list."""
        resps = self._get_responses()
        response = resps[self.i % len(resps)]
        self.i += 1
        return response

    def _simulate_latency(self) -> None:
        """Block for a random duration to simulate LLM thinking time."""
        delay = random.uniform(self.min_latency, self.max_latency)
        time.sleep(delay)

    async def _async_simulate_latency(self) -> None:
        """Async sleep for a random duration to simulate LLM thinking time."""
        delay = random.uniform(self.min_latency, self.max_latency)
        await asyncio.sleep(delay)

    @staticmethod
    def _has_tool_results(messages: List[BaseMessage]) -> bool:
        """Check whether the conversation already contains tool-call results."""
        return any(isinstance(m, ToolMessage) for m in messages)

    @staticmethod
    def _build_tool_call(tools: Sequence[Dict[str, Any]]) -> AIMessage:
        """
        Build an AIMessage containing a single tool call to a randomly
        chosen tool with minimal valid arguments.
        """
        tool = random.choice(tools)
        # Handle both OpenAI-format dicts and LangChain BaseTool objects
        if isinstance(tool, dict):
            func_info = tool.get("function", tool)
            tool_name = func_info.get("name", "unknown_tool")
            args = _generate_tool_args(func_info)
        elif isinstance(tool, BaseTool):
            tool_name = tool.name
            schema = tool.args_schema.schema() if tool.args_schema else {}
            args = _generate_tool_args(schema)
        else:
            tool_name = str(tool)
            args = {}

        tool_call_id = f"mock_{uuid.uuid4().hex[:12]}"
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": tool_call_id,
                    "name": tool_name,
                    "args": args,
                }
            ],
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._simulate_latency()

        tools: List[Dict[str, Any]] = kwargs.get("tools", [])
        if tools and not self._has_tool_results(messages):
            message = self._build_tool_call(tools)
        else:
            message = AIMessage(content=self._next_response())

        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        await self._async_simulate_latency()

        tools: List[Dict[str, Any]] = kwargs.get("tools", [])
        if tools and not self._has_tool_results(messages):
            message = self._build_tool_call(tools)
        else:
            message = AIMessage(content=self._next_response())

        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        self._simulate_latency()

        tools: List[Dict[str, Any]] = kwargs.get("tools", [])
        if tools and not self._has_tool_results(messages):
            message = self._build_tool_call(tools)
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=message.content,
                    tool_calls=message.tool_calls,
                    chunk_position="last",
                )
            )
        else:
            response = self._next_response()
            words = response.split(" ")
            for idx, word in enumerate(words):
                token = word if idx == 0 else " " + word
                is_last = idx == len(words) - 1
                chunk = ChatGenerationChunk(
                    message=AIMessageChunk(
                        content=token,
                        chunk_position="last" if is_last else None,
                    )
                )
                if run_manager:
                    run_manager.on_llm_new_token(token, chunk=chunk)
                yield chunk

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Any:
        await self._async_simulate_latency()

        tools: List[Dict[str, Any]] = kwargs.get("tools", [])
        if tools and not self._has_tool_results(messages):
            message = self._build_tool_call(tools)
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=message.content,
                    tool_calls=message.tool_calls,
                    chunk_position="last",
                )
            )
        else:
            response = self._next_response()
            words = response.split(" ")
            for idx, word in enumerate(words):
                token = word if idx == 0 else " " + word
                is_last = idx == len(words) - 1
                chunk = ChatGenerationChunk(
                    message=AIMessageChunk(
                        content=token,
                        chunk_position="last" if is_last else None,
                    )
                )
                if run_manager:
                    await run_manager.on_llm_new_token(token, chunk=chunk)
                yield chunk

    def bind_tools(
        self,
        tools: Sequence[Dict[str, Any] | type | Callable | BaseTool],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Runnable:
        """Bind tools to this model for tool-calling support."""
        from langchain_core.utils.function_calling import convert_to_openai_tool

        formatted_tools = [convert_to_openai_tool(tool) for tool in tools]
        return self.bind(tools=formatted_tools, **kwargs)

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model_name": "mock-chat-model",
            "responses_count": len(self._get_responses()),
            "min_latency": self.min_latency,
            "max_latency": self.max_latency,
        }
