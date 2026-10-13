
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
# pylint: disable=protected-access

import asyncio
import inspect
import json
import os

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from httpx import AsyncClient
from httpx import MockTransport
from httpx import Request
from httpx import Response
from langchain.agents import create_agent
from langchain_core.load.dump import dumpd
from langchain_core.messages import HumanMessage
from langchain_core.runnables import Runnable
from langchain_core.runnables import RunnableBinding
from langchain_core.runnables.fallbacks import RunnableWithFallbacks
from langchain_core.tools import StructuredTool
from langchain_openai.chat_models.base import ChatOpenAI
from openai.resources.responses import AsyncResponses

from neuro_san.internals.run_context.langchain.core.langchain_openai_function_tool import LangChainOpenAIFunctionTool
from neuro_san.internals.run_context.langchain.llms.tool_strict_chat_openai import ToolStrictChatOpenAI
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import CLASS_TABLE


class TestToolStrictChatOpenAI(TestCase):
    """
    Test cases for ToolStrictChatOpenAI.bind_tools().

    The tests bind tools the way create_agent() does (no strict value) and inspect the tool definitions
    and the request body langchain-openai would send. The one test that runs a real create_agent() loop
    answers the request from an httpx MockTransport, so nothing here reaches the network.
    """

    # The argument schema of a tool with one required and one optional argument. This is the shape an MCP
    # server's tool arrives in: langchain-mcp-adapters turns the server's inputSchema into a StructuredTool
    # with a dict like this as its args_schema. Coded tools get it as the "parameters" of a function spec.
    SEARCH_SCHEMA: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "extraction": {"type": "string", "description": "How much of each page to extract."},
        },
        "required": ["query"],
    }

    # An OpenAI built-in tool, as provider_tools passes them. langchain forwards these dicts untouched.
    WEB_SEARCH_TOOL: Dict[str, Any] = {"type": "web_search"}

    # A structured-answer format in the shape create_agent() passes. langchain converts the inner schema
    # as a function, so it needs a title.
    ANSWER_FORMAT: Dict[str, Any] = {
        "type": "json_schema",
        "json_schema": {
            "name": "answer",
            "schema": {
                "title": "answer",
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    }

    # A minimal successful Responses API body, enough for create_agent() to finish its loop.
    RESPONSES_RESPONSE: Dict[str, Any] = {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "gpt-5.2",
        "output": [{"type": "message", "id": "msg_test", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": "hello", "annotations": []}]}],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
    }

    @override
    def setUp(self) -> None:
        """
        Pins OPENAI_API_KEY to a dummy value and starts the list of captured requests.

        ChatOpenAI builds a synchronous client from the variable, so it is pinned to guarantee no
        real key is ever used.
        """
        env_patcher: Any = patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        self.requests: List[Request] = []

    def _build_llm(self, tool_strict: Optional[bool], use_responses_api: bool = True,
                   capture: bool = False) -> ToolStrictChatOpenAI:
        """
        Builds a chat model that points at a closed local port, so an accidental request fails fast.

        :param tool_strict: The default strict value under test
        :param use_responses_api: Which OpenAI endpoint the model builds its requests for
        :param capture: When True the model sends through an httpx MockTransport that records every
                        request in self.requests and answers with RESPONSES_RESPONSE
        :return: The chat model
        """
        llm_args: Dict[str, Any] = {
            "model": "gpt-5.2",
            "tool_strict": tool_strict,
            "use_responses_api": use_responses_api,
            "openai_api_base": "http://127.0.0.1:9",
            "max_retries": 0,
        }
        if capture:
            llm_args["http_async_client"] = AsyncClient(transport=MockTransport(self._handle_request))
        return ToolStrictChatOpenAI(**llm_args)

    def _handle_request(self, request: Request) -> Response:
        """
        MockTransport handler: records the request and answers like the Responses API would.

        :param request: The request the OpenAI SDK built
        :return: The canned Responses API body
        """
        self.requests.append(request)
        return Response(200, json=self.RESPONSES_RESPONSE, request=request)

    @staticmethod
    def _run_search(**kwargs: Any) -> str:
        """
        Stands in for the search tool's implementation; the tests never call it.

        :param kwargs: The tool arguments
        :return: A fixed answer
        """
        _ = kwargs
        return "no results"

    def _search_tool(self) -> StructuredTool:
        """
        Builds the search tool the way MCP tools reach bind_tools(): a StructuredTool with a dict schema.

        :return: The tool
        """
        return StructuredTool.from_function(func=self._run_search,
                                            name="you_search",
                                            description="Searches the web.",
                                            args_schema=self.SEARCH_SCHEMA)

    def _coded_search_tool(self) -> LangChainOpenAIFunctionTool:
        """
        Builds the search tool the way coded tools reach bind_tools(): from an OpenAI function spec,
        with a pydantic args_schema generated from its parameters.

        :return: The tool
        """
        function_json: Dict[str, Any] = {"name": "you_search",
                                         "description": "Searches the web.",
                                         "parameters": self.SEARCH_SCHEMA}
        # No tool_caller: the tool is only bound, never called.
        return LangChainOpenAIFunctionTool.from_function_json(function_json, tool_caller=None)

    def _search_tool_in_openai_format(self, strict: Optional[bool]) -> Dict[str, Any]:
        """
        Builds the search tool as a dict already in OpenAI tool format.

        :param strict: A strict value to put in the definition, or None for none
        :return: The tool definition
        """
        function: Dict[str, Any] = {"name": "you_search",
                                    "description": "Searches the web.",
                                    "parameters": self.SEARCH_SCHEMA}
        if strict is not None:
            function["strict"] = strict
        return {"type": "function", "function": function}

    def _search_tool_in_responses_format(self) -> Dict[str, Any]:
        """
        Builds the search tool as a dict in the Responses API's flat tool format, without a strict value.

        :return: The tool definition
        """
        return {"type": "function",
                "name": "you_search",
                "description": "Searches the web.",
                "parameters": self.SEARCH_SCHEMA}

    @staticmethod
    def _bound_function(bound: RunnableBinding, index: int = 0) -> Dict[str, Any]:
        """
        Reads one function definition bind_tools() put on the binding, in Chat Completions format.

        :param bound: The result of bind_tools()
        :param index: Which tool to read
        :return: The "function" part of that tool definition
        """
        return bound.kwargs.get("tools")[index].get("function")

    @staticmethod
    def _payload_tool(payload: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
        """
        Reads one tool definition from a request body.

        :param payload: The request body
        :param index: Which tool to read
        :return: The tool definition as the endpoint receives it
        """
        return payload.get("tools")[index]

    @staticmethod
    def _request_payload(bound: RunnableBinding) -> Dict[str, Any]:
        """
        Computes the request body langchain-openai would send for the bound model and one user message.

        :param bound: The result of bind_tools()
        :return: The keyword arguments that would be passed to the OpenAI SDK create() call
        """
        return bound.bound._get_request_payload([HumanMessage("hi")], **bound.kwargs)

    @staticmethod
    def _assert_binds_to_responses_create(payload: Dict[str, Any]) -> None:
        """
        Checks that the payload only uses keyword arguments the Responses API create() accepts.

        :param payload: The request payload to check
        :raises TypeError: If the payload carries a keyword argument create() does not accept
        """
        signature: inspect.Signature = inspect.signature(AsyncResponses.create)
        # The leading None stands in for "self" because create is inspected as an unbound method.
        signature.bind(None, **payload)

    def test_none_sends_no_strict_value(self) -> None:
        """
        With tool_strict None the tool definitions carry no strict key at all, on either endpoint, which
        is what a stock ChatOpenAI sends.
        """
        for use_responses_api in (True, False):
            with self.subTest(use_responses_api=use_responses_api):
                llm: ToolStrictChatOpenAI = self._build_llm(None, use_responses_api)
                bound: RunnableBinding = llm.bind_tools([self._search_tool()])

                self.assertNotIn("strict", self._bound_function(bound))

    def test_false_puts_strict_false_on_every_function_tool(self) -> None:
        """
        With tool_strict False every function tool reaches the Responses API payload with "strict": false,
        its schema untouched, while a built-in tool dict passes through unchanged.
        """
        llm: ToolStrictChatOpenAI = self._build_llm(False)
        bound: RunnableBinding = llm.bind_tools([self._search_tool(), self.WEB_SEARCH_TOOL])
        payload: Dict[str, Any] = self._request_payload(bound)

        search_tool: Dict[str, Any] = self._payload_tool(payload)
        self.assertEqual(search_tool.get("name"), "you_search")
        self.assertIs(search_tool.get("strict"), False)
        self.assertEqual(search_tool.get("parameters").get("required"), ["query"])
        self.assertNotIn("additionalProperties", search_tool.get("parameters"))
        self.assertEqual(self._payload_tool(payload, 1), self.WEB_SEARCH_TOOL)
        self._assert_binds_to_responses_create(payload)

    def test_false_also_applies_on_chat_completions(self) -> None:
        """
        The default is applied regardless of endpoint; Chat Completions carries it inside "function".
        """
        llm: ToolStrictChatOpenAI = self._build_llm(False, use_responses_api=False)
        bound: RunnableBinding = llm.bind_tools([self._search_tool()])
        payload: Dict[str, Any] = self._request_payload(bound)

        self.assertIn("messages", payload)
        self.assertIs(self._payload_tool(payload).get("function").get("strict"), False)

    def test_true_turns_strict_mode_on_and_rewrites_the_schema(self) -> None:
        """
        With tool_strict True langchain marks every property required and forbids additional properties.
        """
        llm: ToolStrictChatOpenAI = self._build_llm(True)
        bound: RunnableBinding = llm.bind_tools([self._search_tool()])
        payload: Dict[str, Any] = self._request_payload(bound)

        search_tool: Dict[str, Any] = self._payload_tool(payload)
        self.assertIs(search_tool.get("strict"), True)
        self.assertEqual(search_tool.get("parameters").get("required"), ["query", "extraction"])
        self.assertIs(search_tool.get("parameters").get("additionalProperties"), False)
        self._assert_binds_to_responses_create(payload)

    def test_a_coded_tool_gets_the_default_too(self) -> None:
        """
        A coded tool carries a pydantic args_schema, which langchain converts through another branch than
        a dict schema; the default lands on it all the same and its optional argument stays optional.
        """
        llm: ToolStrictChatOpenAI = self._build_llm(False)
        bound: RunnableBinding = llm.bind_tools([self._coded_search_tool()])
        payload: Dict[str, Any] = self._request_payload(bound)

        search_tool: Dict[str, Any] = self._payload_tool(payload)
        self.assertEqual(search_tool.get("name"), "you_search")
        self.assertIs(search_tool.get("strict"), False)
        self.assertEqual(search_tool.get("parameters").get("required"), ["query"])
        self._assert_binds_to_responses_create(payload)

    def test_an_explicit_strict_value_wins_over_the_default(self) -> None:
        """
        A strict value passed to bind_tools() is used as given, whatever tool_strict says.
        """
        relaxed: RunnableBinding = self._build_llm(False).bind_tools([self._search_tool()], strict=True)
        strict: RunnableBinding = self._build_llm(True).bind_tools([self._search_tool()], strict=False)

        self.assertIs(self._bound_function(relaxed).get("strict"), True)
        self.assertIs(self._bound_function(strict).get("strict"), False)

    def test_a_response_format_on_chat_completions_leaves_strict_to_langchain(self) -> None:
        """
        When a response_format is bound on Chat Completions, langchain's own rule (strict tools next to a
        response_format) still applies: tool_strict False does not force the tools non-strict, and the
        preformatted definitions langchain would pass through get the same strict True, with the schema
        rewrite, so OpenAI accepts them next to the response_format.
        """
        llm: ToolStrictChatOpenAI = self._build_llm(False, use_responses_api=False)
        bound: RunnableBinding = llm.bind_tools([self._search_tool(),
                                                 self._search_tool_in_openai_format(None),
                                                 self._search_tool_in_responses_format()],
                                                response_format=self.ANSWER_FORMAT)

        self.assertIs(self._bound_function(bound, 0).get("strict"), True)
        nested: Dict[str, Any] = self._bound_function(bound, 1)
        self.assertIs(nested.get("strict"), True)
        self.assertIs(nested.get("parameters").get("additionalProperties"), False)
        flat_tool: Dict[str, Any] = bound.kwargs.get("tools")[2]
        self.assertIs(flat_tool.get("strict"), True)
        self.assertIs(flat_tool.get("parameters").get("additionalProperties"), False)

    def test_an_explicit_false_with_a_response_format_relaxes_every_tool(self) -> None:
        """
        An explicit strict=False from the caller is the one value langchain does not override for a
        response_format on Chat Completions, and the preformatted definitions get that same False, so
        every tool shape in the binding carries the same value.
        """
        llm: ToolStrictChatOpenAI = self._build_llm(True, use_responses_api=False)
        bound: RunnableBinding = llm.bind_tools([self._search_tool(),
                                                 self._search_tool_in_openai_format(None),
                                                 self._search_tool_in_responses_format()],
                                                response_format=self.ANSWER_FORMAT, strict=False)

        self.assertIs(self._bound_function(bound, 0).get("strict"), False)
        self.assertIs(self._bound_function(bound, 1).get("strict"), False)
        self.assertIs(bound.kwargs.get("tools")[2].get("strict"), False)

    def test_a_response_format_on_the_responses_api_keeps_the_default(self) -> None:
        """
        The Responses API has no strict-tools rule for a response_format, so the default still applies
        there and the tools do not fall back to the endpoint's strict attempt.
        """
        llm: ToolStrictChatOpenAI = self._build_llm(False)
        bound: RunnableBinding = llm.bind_tools([self._search_tool()], response_format=self.ANSWER_FORMAT)
        payload: Dict[str, Any] = self._request_payload(bound)

        self.assertIs(self._payload_tool(payload).get("strict"), False)
        self._assert_binds_to_responses_create(payload)

    def test_a_response_format_with_inferred_routing_follows_langchain(self) -> None:
        """
        With use_responses_api null, langchain's response_format rule keys on that configured value, not on
        the endpoint it infers from a reasoning dict. The subclass follows the same rule: where a stock
        ChatOpenAI forces strict for the response_format, so does the subclass, and where it leaves strict
        unset, the default applies. Whether langchain materializes the inferred endpoint on the instance
        differs between langchain-openai releases, so the expectation is read off the stock model.
        """
        llm: ToolStrictChatOpenAI = ToolStrictChatOpenAI(model="gpt-5.2", tool_strict=False,
                                                         use_responses_api=None, reasoning={"effort": "low"},
                                                         openai_api_base="http://127.0.0.1:9", max_retries=0)
        stock: ChatOpenAI = ChatOpenAI(model="gpt-5.2", use_responses_api=None, reasoning={"effort": "low"},
                                       openai_api_base="http://127.0.0.1:9", max_retries=0)

        bound: RunnableBinding = llm.bind_tools([self._search_tool()], response_format=self.ANSWER_FORMAT)
        stock_bound: RunnableBinding = stock.bind_tools([self._search_tool()], response_format=self.ANSWER_FORMAT)

        # The reasoning dict makes langchain route the request to the Responses API either way.
        self.assertIs(llm._use_responses_api(llm._default_params), True)
        stock_strict: Optional[bool] = self._bound_function(stock_bound).get("strict")
        expected: bool = stock_strict if stock_strict is not None else False
        self.assertIs(self._bound_function(bound).get("strict"), expected)

    def test_preformatted_function_tools_get_the_default_unless_they_set_strict(self) -> None:
        """
        langchain passes a definition already in OpenAI tool format through unchanged, so the subclass
        writes the default into it itself, in the nested and in the flat shape, and leaves a definition
        that names its own strict alone.
        """
        llm: ToolStrictChatOpenAI = self._build_llm(False)
        bound: RunnableBinding = llm.bind_tools([self._search_tool_in_openai_format(None),
                                                 self._search_tool_in_openai_format(True),
                                                 self._search_tool_in_responses_format()])
        payload: Dict[str, Any] = self._request_payload(bound)

        self.assertIs(self._bound_function(bound, 0).get("strict"), False)
        self.assertIs(self._bound_function(bound, 1).get("strict"), True)
        flat_tool: Dict[str, Any] = bound.kwargs.get("tools")[2]
        self.assertEqual(flat_tool.get("type"), "function")
        self.assertEqual(flat_tool.get("name"), "you_search")
        self.assertIs(flat_tool.get("strict"), False)
        # On the wire all three are function tools carrying their value.
        for index in range(3):
            with self.subTest(index=index):
                expected: bool = index == 1
                self.assertIs(self._payload_tool(payload, index).get("strict"), expected)
        self._assert_binds_to_responses_create(payload)

    def test_true_rewrites_the_schema_of_a_preformatted_function_tool_too(self) -> None:
        """
        A preformatted definition goes through langchain's converter, so tool_strict True gives it the
        schema rewrite strict mode needs, not only the flag.
        """
        llm: ToolStrictChatOpenAI = self._build_llm(True)
        bound: RunnableBinding = llm.bind_tools([self._search_tool_in_openai_format(None)])

        function: Dict[str, Any] = self._bound_function(bound)
        self.assertIs(function.get("strict"), True)
        self.assertEqual(function.get("parameters").get("required"), ["query", "extraction"])
        self.assertIs(function.get("parameters").get("additionalProperties"), False)

    def test_fallbacks_get_the_same_default(self) -> None:
        """
        bind_tools() on a model with fallbacks binds the fallbacks too, each with its own default.

        RunnableWithFallbacks only forwards a method whose return type is a Runnable, so this also
        guards the return annotation of the override.
        """
        primary: ToolStrictChatOpenAI = self._build_llm(False)
        fallback: ToolStrictChatOpenAI = self._build_llm(False, use_responses_api=False)
        stock: ChatOpenAI = ChatOpenAI(model="gpt-4o", openai_api_base="http://127.0.0.1:9", max_retries=0)
        with_fallbacks: RunnableWithFallbacks = primary.with_fallbacks([fallback, stock])

        bound: Any = with_fallbacks.bind_tools([self._search_tool()])

        self.assertIsInstance(bound, RunnableWithFallbacks)
        self.assertIs(self._bound_function(bound.runnable).get("strict"), False)
        self.assertIs(self._bound_function(bound.fallbacks[0]).get("strict"), False)
        # A stock ChatOpenAI fallback has no default and keeps sending nothing.
        self.assertNotIn("strict", self._bound_function(bound.fallbacks[1]))

    def test_create_agent_sends_the_default_on_the_wire(self) -> None:
        """
        langchain's create_agent() binds tools at request time without a strict value. The request it
        puts on the wire carries "strict": false on the function tool, which is what the default is for.
        """
        llm: ToolStrictChatOpenAI = self._build_llm(False, capture=True)
        agent: Runnable = create_agent(model=llm, tools=[self._search_tool()])

        asyncio.run(agent.ainvoke({"messages": [HumanMessage("hi")]}))

        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.requests[0].url.path.endswith("/responses"))
        body: Dict[str, Any] = json.loads(self.requests[0].content)
        sent_tool: Dict[str, Any] = self._payload_tool(body)
        self.assertEqual(sent_tool.get("name"), "you_search")
        self.assertIs(sent_tool.get("strict"), False)
        self.assertEqual(sent_tool.get("parameters").get("required"), ["query"])

    def test_serialized_class_name_is_booked_as_openai(self) -> None:
        """
        langchain serializes the subclass under its own name, which token accounting maps to "openai".
        """
        llm: ToolStrictChatOpenAI = self._build_llm(False)

        class_name: str = dumpd(llm).get("id")[-1]

        self.assertEqual(class_name, "ToolStrictChatOpenAI")
        self.assertEqual(CLASS_TABLE.get(class_name), "openai")
