
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
"""
See class comment for details.
"""

from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from json import dumps

from langchain_core.messages import AIMessageChunk
from langchain_core.messages import BaseMessage
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.utils.function_calling import convert_to_openai_tool


class OpenAiWireFormat:
    """
    Translation between langchain's message objects and the OpenAI-compatible
    /chat/completions wire format.

    Kept apart from the chat model so the protocol details can be read, and
    tested, without a transport or an event loop in the way.
    """

    @staticmethod
    def convert_tools(tools: List[Any]) -> List[Dict[str, Any]]:
        """
        Convert tools into the wire shape the endpoint expects.

        :param tools: Tools in any form langchain can convert
        :return: The tools as OpenAI tool dictionaries
        """
        return [convert_to_openai_tool(tool) for tool in tools]

    @staticmethod
    def build_request(model_name: str, messages: List[BaseMessage],
                      tools: Optional[List[Dict[str, Any]]] = None,
                      stop: Optional[List[str]] = None,
                      extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Build the request body for one streaming chat completion.

        :param model_name: The model id to ask for
        :param messages: The prompt, as langchain messages
        :param tools: Tools in wire shape, if any
        :param stop: Stop sequences, if any
        :param extra: Extra body fields to merge in
        :return: The JSON-serialisable request body
        """
        body: Dict[str, Any] = {
            "model": model_name,
            "messages": [OpenAiWireFormat.convert_message(message) for message in messages],
            "stream": True,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if stop:
            body["stop"] = stop
        if extra:
            body.update(extra)
        return body

    @staticmethod
    def convert_message(message: BaseMessage) -> Dict[str, Any]:
        """
        Convert one langchain message into its wire form.

        :param message: The message to convert
        :return: The message as a wire dictionary
        """
        role: str = OpenAiWireFormat.convert_role(message)
        wire: Dict[str, Any] = {"role": role, "content": message.content or ""}

        # A tool result has to say which call it answers.
        tool_call_id: str = getattr(message, "tool_call_id", None)
        if tool_call_id is not None:
            wire["tool_call_id"] = tool_call_id

        # An assistant turn that called tools has to carry those calls back,
        # or the server cannot match the tool results that follow.
        calls: List[Dict[str, Any]] = list(getattr(message, "tool_calls", []) or [])
        if calls:
            wire["tool_calls"] = [
                {
                    "id": call.get("id"),
                    "type": "function",
                    "function": {"name": call.get("name"),
                                 "arguments": dumps(call.get("args") or {})},
                }
                for call in calls
            ]
        return wire

    @staticmethod
    def convert_role(message: BaseMessage) -> str:
        """
        :param message: The message whose role is wanted
        :return: The wire role name for that message
        """
        roles: Dict[str, str] = {
            "human": "user",
            "ai": "assistant",
            "system": "system",
            "tool": "tool",
            "function": "function",
        }
        return roles.get(message.type, "user")

    @staticmethod
    def build_chunk(payload: Dict[str, Any],
                    tool_calls: Dict[int, Dict[str, Any]]) -> Optional[ChatGenerationChunk]:
        """
        Turn one streamed event into a chunk, accumulating any tool-call parts.

        Tool calls arrive split across events -- a name in one, a few
        characters of JSON arguments in the next -- keyed by an index that says
        which call each fragment belongs to. They are accumulated into
        tool_calls rather than yielded, because a half-built call is not usable.

        :param payload: One decoded event from the stream
        :param tool_calls: Accumulator, keyed by the call's index
        :return: A chunk carrying this event's text, or None if the event only
                 advanced a tool call
        """
        choices: List[Dict[str, Any]] = payload.get("choices") or []
        if not choices:
            return None
        delta: Dict[str, Any] = choices[0].get("delta") or {}

        for fragment in delta.get("tool_calls") or []:
            index: int = fragment.get("index", 0)
            call: Dict[str, Any] = tool_calls.setdefault(
                index, {"id": None, "name": "", "args": ""})
            if fragment.get("id"):
                call["id"] = fragment["id"]
            function: Dict[str, Any] = fragment.get("function") or {}
            if function.get("name"):
                call["name"] += function["name"]
            if function.get("arguments"):
                call["args"] += function["arguments"]

        content: str = delta.get("content")
        if not content:
            return None
        return ChatGenerationChunk(message=AIMessageChunk(content=content))

    @staticmethod
    def build_tool_call_chunk(tool_calls: Dict[int, Dict[str, Any]]) -> ChatGenerationChunk:
        """
        Emit the accumulated tool calls as one final chunk.

        :param tool_calls: The accumulator filled by build_chunk()
        :return: A chunk carrying every tool call the stream asked for
        """
        chunks: List[Dict[str, Any]] = [
            tool_call_chunk(name=call["name"], args=call["args"], id=call["id"], index=index)
            for index, call in sorted(tool_calls.items())
        ]
        return ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=chunks))
