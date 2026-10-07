
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
Unit tests for OpenAiWireChatModel, the SDK-free chat model.

Driven through FakeChatTransport so the wire format, the SSE framing and the
tool-call assembly are exercised with no server and no network. The framing
here is deliberately awkward in places -- a tool call split mid-argument, a
keep-alive comment, a blank line -- because a real endpoint will not produce
those on demand, and they are exactly what the parser has to survive.
"""

from typing import Any
from typing import Dict
from typing import List
from unittest import IsolatedAsyncioTestCase

from json import dumps

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage

from neuro_san.internals.run_context.langchain.llms.wire.openai_wire_chat_model import OpenAiWireChatModel
from tests.neuro_san.internals.run_context.langchain.llms.wire.fake_chat_transport import FakeChatTransport


class TestOpenAiWireChatModel(IsolatedAsyncioTestCase):
    """
    Tests OpenAiWireChatModel against canned response bodies.
    """

    @staticmethod
    def text_event(content: str) -> str:
        """
        :param content: The text fragment the event carries
        :return: One SSE data line carrying that fragment
        """
        return "data: " + dumps({"choices": [{"delta": {"content": content}}]})

    @staticmethod
    def tool_event(index: int, call_id: str = None, name: str = None, args: str = None) -> str:
        """
        :param index: Which tool call this fragment belongs to
        :param call_id: The call id, on the fragment that carries it
        :param name: Part of the function name, if any
        :param args: Part of the JSON arguments, if any
        :return: One SSE data line carrying that tool-call fragment
        """
        function: Dict[str, Any] = {}
        if name is not None:
            function["name"] = name
        if args is not None:
            function["arguments"] = args
        fragment: Dict[str, Any] = {"index": index, "function": function}
        if call_id is not None:
            fragment["id"] = call_id
        return "data: " + dumps({"choices": [{"delta": {"tool_calls": [fragment]}}]})

    def make_model(self, lines: List[str]) -> OpenAiWireChatModel:
        """
        :param lines: The response body lines the transport should replay
        :return: A model wired to a FakeChatTransport replaying them
        """
        # pylint: disable=attribute-defined-outside-init
        self.transport = FakeChatTransport(lines)
        return OpenAiWireChatModel(transport=self.transport, base_url="http://host/v1",
                                   model_name="a-model", api_key="secret")

    async def test_text_is_streamed_chunk_by_chunk(self) -> None:
        """
        Each data event becomes one chunk, and the keep-alive noise between
        them is skipped rather than parsed.
        """
        model = self.make_model([self.text_event("Hel"), "", ": keep-alive",
                                 self.text_event("lo"), "data: [DONE]"])

        pieces: List[str] = []
        async for chunk in model.astream([HumanMessage(content="hi")]):
            if chunk.content:
                pieces.append(chunk.content)

        self.assertEqual(pieces, ["Hel", "lo"])

    async def test_ainvoke_joins_the_stream(self) -> None:
        """
        The server is always asked to stream, so a single reply is the stream
        added back up.
        """
        model = self.make_model([self.text_event("one "), self.text_event("two"),
                                 "data: [DONE]"])

        message = await model.ainvoke([HumanMessage(content="hi")])

        self.assertEqual(message.content, "one two")
        self.assertTrue(self.transport.requests[0]["body"]["stream"])

    async def test_a_tool_call_split_across_events_is_reassembled(self) -> None:
        """
        Tool calls arrive in fragments -- the name in one event, the arguments
        a few characters at a time after it -- and are only usable once the
        stream ends. A half-built call must never be emitted.
        """
        model = self.make_model([
            self.tool_event(0, call_id="call_1", name="get_"),
            self.tool_event(0, name="weather"),
            self.tool_event(0, args='{"ci'),
            self.tool_event(0, args='ty": "Paris"}'),
            "data: [DONE]",
        ])

        message = await model.ainvoke([HumanMessage(content="weather?")])

        self.assertEqual(len(message.tool_calls), 1)
        self.assertEqual(message.tool_calls[0]["name"], "get_weather")
        self.assertEqual(message.tool_calls[0]["args"], {"city": "Paris"})
        self.assertEqual(message.tool_calls[0]["id"], "call_1")

    async def test_two_tool_calls_stay_separate(self) -> None:
        """
        Fragments are keyed by index, so interleaved calls must not merge.
        """
        model = self.make_model([
            self.tool_event(0, call_id="a", name="first", args="{}"),
            self.tool_event(1, call_id="b", name="second"),
            self.tool_event(1, args="{}"),
            "data: [DONE]",
        ])

        message = await model.ainvoke([HumanMessage(content="both")])

        self.assertEqual([call["name"] for call in message.tool_calls], ["first", "second"])
        self.assertEqual([call["id"] for call in message.tool_calls], ["a", "b"])

    async def test_the_request_carries_key_and_messages_in_wire_shape(self) -> None:
        """
        The key goes in a header and never the URL, and langchain's message
        objects reach the server as wire roles.
        """
        model = self.make_model(["data: [DONE]"])

        await model.ainvoke([HumanMessage(content="ask"), AIMessage(content="answer")])

        request: Dict[str, Any] = self.transport.requests[0]
        self.assertEqual(request["url"], "http://host/v1/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret")
        self.assertNotIn("secret", request["url"])
        self.assertEqual([message["role"] for message in request["body"]["messages"]],
                         ["user", "assistant"])

    async def test_a_tool_result_carries_its_call_id_back(self) -> None:
        """
        A tool result the server cannot match to its call is useless, so the
        tool_call_id has to survive the conversion.
        """
        model = self.make_model(["data: [DONE]"])

        await model.ainvoke([ToolMessage(content="sunny", tool_call_id="call_1")])

        message: Dict[str, Any] = self.transport.requests[0]["body"]["messages"][0]
        self.assertEqual(message["role"], "tool")
        self.assertEqual(message["tool_call_id"], "call_1")

    async def test_malformed_events_are_skipped_not_fatal(self) -> None:
        """
        A truncated or non-JSON data line should cost that event, not the
        whole stream.
        """
        model = self.make_model([self.text_event("good "), "data: {not json",
                                 self.text_event("still good"), "data: [DONE]"])

        message = await model.ainvoke([HumanMessage(content="hi")])

        self.assertEqual(message.content, "good still good")

    async def test_there_is_no_synchronous_path(self) -> None:
        """
        A synchronous call would block the loop this model exists to share, so
        it refuses rather than quietly running the async path in a thread.
        """
        model = self.make_model([self.text_event("hi")])

        with self.assertRaisesRegex(NotImplementedError, "no synchronous path"):
            model.invoke([HumanMessage(content="hi")])
