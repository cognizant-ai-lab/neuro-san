
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
from typing import AsyncIterator
from typing import Dict
from typing import List
from typing import Optional

from json import JSONDecodeError
from json import loads

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.outputs import ChatResult
from pydantic import ConfigDict
from pydantic import Field

from neuro_san.internals.run_context.langchain.llms.wire.chat_transport import ChatTransport
from neuro_san.internals.run_context.langchain.llms.wire.openai_wire_format import OpenAiWireFormat


class OpenAiWireChatModel(BaseChatModel):
    """
    A chat model that speaks the OpenAI-compatible /chat/completions wire
    protocol directly, with no provider SDK underneath it.

    Why this exists: the usual stack is langchain-openai on the openai SDK on
    httpx on sockets, and in a browser none of the lower three work -- Pyodide
    has no sockets, and the SDK moves some calls onto a worker thread that does
    not exist there. Rather than tunnel that stack through the browser's
    fetch(), this skips it: the wire protocol is small, and speaking it takes
    about as much code as adapting the SDK would.

    This is the Python counterpart of the hand-written JavaScript runtime's
    LlmClient, and it makes the same trade: Chat Completions only, always
    streaming. There is no Responses API support here, so models that need it
    for tool calling with reasoning are out of scope.

    Only _astream() is implemented, deliberately. BaseChatModel's default
    _astream runs a subclass's _stream in a worker thread, which is the very
    thing this class exists to avoid, so implementing _stream would reintroduce
    the problem through the back door.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # The transport that actually moves the bytes. Injected rather than chosen
    # here, so this class never has to ask what runtime it is in.
    transport: ChatTransport = Field(...)

    # Base URL of an OpenAI-compatible endpoint, without a trailing slash.
    base_url: str = Field(...)

    # The model id to ask for.
    model_name: str = Field(...)

    # Sent as "Authorization: Bearer ...". Never placed in the URL.
    api_key: Optional[str] = Field(default=None)

    # Tools bound via bind_tools(), in OpenAI wire shape.
    wire_tools: Optional[List[Dict[str, Any]]] = Field(default=None)

    @property
    def _llm_type(self) -> str:
        """
        :return: The identifier langchain uses for this model class
        """
        return "openai-wire"

    def bind_tools(self, tools: List[Any], **kwargs: Any) -> "OpenAiWireChatModel":
        """
        Bind tools to this model, as langchain's tool-calling path expects.

        :param tools: The tools to bind, in any form langchain can convert
        :param kwargs: Accepted and ignored, for signature compatibility
        :return: A copy of this model carrying the converted tools
        """
        _ = kwargs
        return self.model_copy(update={"wire_tools": OpenAiWireFormat.convert_tools(tools)})

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """
        Stream the model's reply, one chunk per server-sent event.

        :param messages: The prompt, as langchain messages
        :param stop: Stop sequences, forwarded to the server
        :param run_manager: The callback manager to report new tokens to
        :param kwargs: Any extra body fields to forward
        :return: An async iterator of ChatGenerationChunk
        """
        # pylint sees the pydantic Field() descriptors rather than the values
        # they resolve to at runtime, so it reads self.base_url and
        # self.transport as FieldInfo here.
        # pylint: disable=no-member
        body: Dict[str, Any] = OpenAiWireFormat.build_request(
            model_name=self.model_name, messages=messages,
            tools=self.wire_tools, stop=stop, extra=kwargs)

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url: str = f"{self.base_url.rstrip('/')}/chat/completions"

        tool_calls: Dict[int, Dict[str, Any]] = {}
        async for line in self.transport.stream_lines(url, headers, body):
            payload: Dict[str, Any] = self._parse_sse_line(line)
            if payload is None:
                continue

            chunk: ChatGenerationChunk = OpenAiWireFormat.build_chunk(payload, tool_calls)
            if chunk is None:
                continue
            if run_manager is not None and chunk.message.content:
                await run_manager.on_llm_new_token(chunk.message.content, chunk=chunk)
            yield chunk

        # Tool calls arrive in fragments across many events and are only whole
        # once the stream ends, so they are emitted as a final chunk.
        if tool_calls:
            yield OpenAiWireFormat.build_tool_call_chunk(tool_calls)

    @staticmethod
    def _parse_sse_line(line: str) -> Optional[Dict[str, Any]]:
        """
        Turn one line of the response body into an event payload.

        :param line: A single line from the response body
        :return: The decoded JSON payload, or None for anything that is not a
                 data event: blank keep-alive lines, comments, the [DONE]
                 sentinel, and any fragment that does not parse
        """
        stripped: str = line.strip()
        if not stripped or not stripped.startswith("data:"):
            return None
        payload: str = stripped[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            return None
        try:
            return loads(payload)
        except JSONDecodeError:
            return None

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """
        Refuse to run synchronously.

        BaseChatModel requires this method to exist, but there is no honest
        implementation here: completing it would mean blocking the caller's
        thread on network I/O, and where this class is meant to run -- a single
        shared event loop, with no worker threads -- that blocks everything.
        Use ainvoke() or astream().

        :param messages: Unused
        :param stop: Unused
        :param run_manager: Unused
        :param kwargs: Unused
        :return: Never returns
        """
        _ = messages, stop, run_manager, kwargs
        raise NotImplementedError(
            f"{self.__class__.__name__} has no synchronous path: completing one would block the "
            "event loop it shares with everything else. Use ainvoke() or astream()."
        )

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """
        Produce a single reply by consuming the stream and joining it.

        The server is always asked to stream, as the JavaScript runtime does,
        so this is the streaming path with the chunks added up.

        :param messages: The prompt, as langchain messages
        :param stop: Stop sequences, forwarded to the server
        :param run_manager: The callback manager to report new tokens to
        :param kwargs: Any extra body fields to forward
        :return: A ChatResult holding the assembled reply
        """
        merged: Optional[AIMessageChunk] = None
        async for chunk in self._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            merged = chunk.message if merged is None else merged + chunk.message

        if merged is None:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])

        message: AIMessage = AIMessage(
            content=merged.content,
            additional_kwargs=merged.additional_kwargs,
            tool_calls=list(getattr(merged, "tool_calls", []) or []),
            response_metadata=merged.response_metadata,
            usage_metadata=getattr(merged, "usage_metadata", None),
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
