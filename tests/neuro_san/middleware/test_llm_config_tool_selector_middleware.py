
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
from logging import getLogger
from typing import Any
from typing import Dict
from typing import List
from unittest import IsolatedAsyncioTestCase
from unittest import TestCase

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware import LLMToolSelectorMiddleware
from langchain.agents.middleware.types import ModelRequest
from langchain.agents.middleware.types import ModelResponse
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool

from neuro_san.middleware.llm_config_tool_selector_middleware import ADVERTISED_TOOLS_KEY
from neuro_san.middleware.llm_config_tool_selector_middleware import LlmConfigToolSelectorMiddleware


class ToolCallingFakeModel(FakeMessagesListChatModel):
    """
    Scripted main model that plays back canned responses and tolerates tool binding.
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ToolCallingFakeModel":
        """
        The default BaseChatModel implementation raises NotImplementedError.
        Scripted responses don't care what tools are bound.
        """
        _ = tools, kwargs
        return self


class FakeSelectionModel(FakeMessagesListChatModel):
    """
    Scripted selection model that always selects a fixed set of tools,
    regardless of what the selection prompt asks.
    """

    selected: List[str] = []

    def with_structured_output(self, schema: Any, **kwargs: Any) -> RunnableLambda:
        """
        The middleware calls this to get structured {"tools": [...]} output.
        """
        _ = schema, kwargs
        return RunnableLambda(lambda _input: {"tools": list(self.selected)})


class MetadataStrippingMiddleware(AgentMiddleware):
    """
    Mimics langchain's PIIMiddleware redaction behavior: after the model runs,
    the last AIMessage is rebuilt (same id and tool_calls) WITHOUT copying
    response_metadata, and replaces the original in state by id.
    """

    async def aafter_model(self, state: Any, runtime: Any) -> Any:
        """
        Rebuild the last AIMessage without its response_metadata.
        """
        _ = runtime
        last: Any = state["messages"][-1]
        if not isinstance(last, AIMessage):
            return None
        rebuilt = AIMessage(content=last.content, id=last.id, tool_calls=last.tool_calls)
        return {"messages": [rebuilt]}


def build_middleware(selected: List[str],
                     sly_data: Dict[str, Any] = None,
                     origin_str: str = None,
                     unadvertised_policy: str = "allow") -> LlmConfigToolSelectorMiddleware:
    """
    Construct the middleware without an ActivationCapsule/real LLM by initializing
    through the langchain superclass directly with a scripted selection model.
    """
    middleware = LlmConfigToolSelectorMiddleware.__new__(LlmConfigToolSelectorMiddleware)
    selection_model = FakeSelectionModel(responses=[], selected=selected)
    LLMToolSelectorMiddleware.__init__(middleware, model=selection_model)
    middleware.logger = getLogger("test")
    middleware._initialize_enforcement(sly_data, origin_str, unadvertised_policy)
    return middleware


@tool
def safe_echo(text: str) -> str:
    """Echoes the text back."""
    return text


@tool
def canary() -> str:
    """A sensitive tool that should not run when de-selected."""
    return "canary executed"


class TestLlmConfigToolSelectorMiddleware(TestCase):
    """
    Unit tests for execution-time enforcement of tool selection.
    """

    def test_stamp_advertised_tools(self):
        """
        The advertised tool names are recorded per tool call id the model emitted.
        """
        middleware = build_middleware(selected=["safe_echo"])
        request = ModelRequest(
            model=ToolCallingFakeModel(responses=[]),
            messages=[HumanMessage("hi")],
            tools=[safe_echo, canary],
        )
        response = ModelResponse(result=[
            AIMessage(
                content="",
                tool_calls=[{"name": "canary", "args": {}, "id": "call_1", "type": "tool_call"}],
            ),
        ])

        middleware._stamp_advertised_tools(request, response)

        self.assertEqual(middleware.advertised_tools, {"call_1": ["safe_echo", "canary"]})

    def test_stamp_records_nothing_without_tool_calls(self):
        """
        AIMessages without tool calls leave no bookkeeping behind.
        """
        middleware = build_middleware(selected=["safe_echo"])
        request = ModelRequest(
            model=ToolCallingFakeModel(responses=[]),
            messages=[HumanMessage("hi")],
            tools=[safe_echo],
        )
        response = ModelResponse(result=[AIMessage("hello")])

        middleware._stamp_advertised_tools(request, response)

        self.assertEqual(middleware.advertised_tools, {})

    def test_stamp_uses_shared_sly_data(self):
        """
        When sly_data and origin_str are provided, the bookkeeping lives in the
        shared sly_data dictionary under the middleware's namespace.
        """
        sly_data: Dict[str, Any] = {}
        middleware = build_middleware(selected=["safe_echo"], sly_data=sly_data, origin_str="network.agent")

        middleware.advertised_tools["call_1"] = ["safe_echo"]

        self.assertEqual(sly_data, {ADVERTISED_TOOLS_KEY: {"network.agent": {"call_1": ["safe_echo"]}}})

    def _tool_call_request(self, name: str, call_id: str) -> ToolCallRequest:
        """
        Helper to build a ToolCallRequest for the given tool call.
        """
        return ToolCallRequest(
            tool_call={"name": name, "args": {}, "id": call_id, "type": "tool_call"},
            tool=None,
            state={"messages": []},
            runtime=None,
        )

    def test_deny_unadvertised_tool_call(self):
        """
        A tool call whose recorded advertisement omits the tool's name is denied.
        """
        middleware = build_middleware(selected=["safe_echo"])
        middleware.advertised_tools["call_1"] = ["safe_echo"]
        request = self._tool_call_request(name="canary", call_id="call_1")

        denial = middleware._deny_unadvertised_tool_call(request)

        self.assertIsInstance(denial, ToolMessage)
        self.assertEqual(denial.status, "error")
        self.assertEqual(denial.tool_call_id, "call_1")
        # The denial names the advertised tools so the model can retry with a valid one.
        self.assertIn("Try one of [safe_echo]", denial.content)

    def test_deny_tool_call_without_id(self):
        """
        Providers may omit tool call ids (ToolCall.id is Optional). The denial path
        must still return a valid error ToolMessage instead of raising a pydantic
        ValidationError over its required string tool_call_id.
        """
        middleware = build_middleware(selected=["safe_echo"])
        middleware.advertised_tools[None] = ["safe_echo"]
        request = self._tool_call_request(name="canary", call_id=None)

        denial = middleware._deny_unadvertised_tool_call(request)

        self.assertIsInstance(denial, ToolMessage)
        self.assertEqual(denial.status, "error")
        self.assertEqual(denial.tool_call_id, "unknown")

    def test_allow_advertised_tool_call(self):
        """
        A tool call whose name was advertised on its originating model call is allowed.
        """
        middleware = build_middleware(selected=["safe_echo"])
        middleware.advertised_tools["call_1"] = ["safe_echo"]
        request = self._tool_call_request(name="safe_echo", call_id="call_1")

        self.assertIsNone(middleware._deny_unadvertised_tool_call(request))

    def test_allow_unrecorded_tool_call(self):
        """
        With the default "allow" policy, tool calls with no recorded advertisement
        (e.g. produced by another middleware short-circuiting the model call)
        are allowed for backward compatibility.
        """
        middleware = build_middleware(selected=["safe_echo"])
        request = self._tool_call_request(name="canary", call_id="call_1")

        self.assertIsNone(middleware._deny_unadvertised_tool_call(request))

    def test_deny_unrecorded_tool_call_with_deny_policy(self):
        """
        With unadvertised_policy="deny", tool calls with no recorded advertisement
        are rejected instead of allowed.
        """
        middleware = build_middleware(selected=["safe_echo"], unadvertised_policy="deny")
        request = self._tool_call_request(name="canary", call_id="call_1")

        denial = middleware._deny_unadvertised_tool_call(request)

        self.assertIsInstance(denial, ToolMessage)
        self.assertEqual(denial.status, "error")
        self.assertIn("no recorded tool selection", denial.content)

    def test_invalid_unadvertised_policy_raises(self):
        """
        A typo in unadvertised_policy fails at construction time, not silently at runtime.
        """
        with self.assertRaises(ValueError):
            build_middleware(selected=["safe_echo"], unadvertised_policy="denny")


class TestLlmConfigToolSelectorMiddlewareAsync(IsolatedAsyncioTestCase):
    """
    End-to-end enforcement tests through the async path
    (awrap_model_call/awrap_tool_call), which is how neuro-san invokes agents.
    """

    def setUp(self):
        self.canary_ran: List[bool] = []

        @tool
        def counting_canary() -> str:
            """A sensitive tool that should not run when de-selected."""
            self.canary_ran.append(True)
            return "canary executed"

        self.counting_canary = counting_canary

        self.main_model = ToolCallingFakeModel(responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "counting_canary", "args": {}, "id": "call_1", "type": "tool_call"}],
            ),
            AIMessage(content="done"),
        ])

    def assert_canary_denied(self, result: Dict[str, Any]):
        """
        Assert the de-selected tool did not run and the model got the error ToolMessage.
        """
        self.assertEqual(self.canary_ran, [], "De-selected tool must not execute")

        tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0].status, "error")
        self.assertIn("was not among the tools selected", tool_messages[0].content)

    async def test_deselected_tool_does_not_execute_in_agent(self):
        """
        End-to-end through create_agent: the selection model selects only safe_echo,
        the (scripted) main model nonetheless emits a tool call for the de-selected
        counting_canary tool, and the executor must not run it.

        This is the advertise-only desync from GHSA-3xg4-wfwr-gc2g Finding 1:
        without enforcement, the executor runs every configured tool regardless
        of what the selector advertised.
        """
        sly_data: Dict[str, Any] = {}
        middleware = build_middleware(selected=["safe_echo"], sly_data=sly_data, origin_str="test.agent")
        agent = create_agent(
            model=self.main_model,
            tools=[safe_echo, self.counting_canary],
            middleware=[middleware],
        )

        result = await agent.ainvoke({"messages": [HumanMessage("please run the canary tool")]})

        self.assert_canary_denied(result)

        # The bookkeeping for the tool call lives in the shared sly_data.
        self.assertEqual(sly_data[ADVERTISED_TOOLS_KEY]["test.agent"], {"call_1": ["safe_echo"]})

    async def test_enforcement_survives_message_rewriting_middleware(self):
        """
        Regression test: middleware that rebuild the tool-calling AIMessage without
        copying response_metadata (langchain's PIIMiddleware redaction does exactly
        this) must not disable enforcement.  The bookkeeping lives in sly_data,
        outside of langgraph agent state, so message rewriting cannot disturb it.
        """
        middleware = build_middleware(selected=["safe_echo"])
        agent = create_agent(
            model=self.main_model,
            tools=[safe_echo, self.counting_canary],
            middleware=[middleware, MetadataStrippingMiddleware()],
        )

        result = await agent.ainvoke({"messages": [HumanMessage("please run the canary tool")]})

        self.assert_canary_denied(result)
