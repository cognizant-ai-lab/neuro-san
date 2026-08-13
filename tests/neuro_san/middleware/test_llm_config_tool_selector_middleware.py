
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
from typing import List
from unittest import IsolatedAsyncioTestCase
from unittest import TestCase

from langchain.agents import create_agent
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


def build_middleware(selected: List[str]) -> LlmConfigToolSelectorMiddleware:
    """
    Construct the middleware without an ActivationCapsule/real LLM by initializing
    through the langchain superclass directly with a scripted selection model.
    """
    middleware = LlmConfigToolSelectorMiddleware.__new__(LlmConfigToolSelectorMiddleware)
    selection_model = FakeSelectionModel(responses=[], selected=selected)
    LLMToolSelectorMiddleware.__init__(middleware, model=selection_model)
    middleware.logger = getLogger("test")
    return middleware


@tool
def safe_echo(text: str) -> str:
    """Echoes the text back."""
    return text


class TestLlmConfigToolSelectorMiddleware(TestCase):
    """
    Unit tests for execution-time enforcement of tool selection.
    """

    def setUp(self):
        self.canary_ran: bool = False

        @tool
        def canary() -> str:
            """A sensitive tool that should not run when de-selected."""
            self.canary_ran = True
            return "canary executed"

        self.canary = canary

    def test_stamp_advertised_tools(self):
        """
        awrap_model_call's handler wrapper records the advertised tool names
        on the AIMessage the model produced.
        """
        middleware = build_middleware(selected=["safe_echo"])
        request = ModelRequest(
            model=ToolCallingFakeModel(responses=[]),
            messages=[HumanMessage("hi")],
            tools=[safe_echo, self.canary],
        )
        response = ModelResponse(result=[AIMessage("hello")])

        middleware._stamp_advertised_tools(request, response)

        self.assertEqual(response.result[0].response_metadata[ADVERTISED_TOOLS_KEY],
                         ["safe_echo", "canary"])

    def _tool_call_request(self, messages: List[Any], name: str, call_id: str) -> ToolCallRequest:
        """
        Helper to build a ToolCallRequest with the given state messages.
        """
        return ToolCallRequest(
            tool_call={"name": name, "args": {}, "id": call_id, "type": "tool_call"},
            tool=None,
            state={"messages": messages},
            runtime=None,
        )

    def test_deny_unadvertised_tool_call(self):
        """
        A tool call whose origin AIMessage was stamped without the tool's name is denied.
        """
        middleware = build_middleware(selected=["safe_echo"])
        origin = AIMessage(
            content="",
            tool_calls=[{"name": "canary", "args": {}, "id": "call_1", "type": "tool_call"}],
            response_metadata={ADVERTISED_TOOLS_KEY: ["safe_echo"]},
        )
        request = self._tool_call_request([origin], name="canary", call_id="call_1")

        denial = middleware._deny_unadvertised_tool_call(request)

        self.assertIsInstance(denial, ToolMessage)
        self.assertEqual(denial.status, "error")
        self.assertEqual(denial.tool_call_id, "call_1")

    def test_allow_advertised_tool_call(self):
        """
        A tool call whose name was advertised on its originating model call is allowed.
        """
        middleware = build_middleware(selected=["safe_echo"])
        origin = AIMessage(
            content="",
            tool_calls=[{"name": "safe_echo", "args": {"text": "x"}, "id": "call_1", "type": "tool_call"}],
            response_metadata={ADVERTISED_TOOLS_KEY: ["safe_echo"]},
        )
        request = self._tool_call_request([origin], name="safe_echo", call_id="call_1")

        self.assertIsNone(middleware._deny_unadvertised_tool_call(request))

    def test_allow_unstamped_tool_call(self):
        """
        Tool calls from AIMessages without a stamp (e.g. pre-upgrade checkpointed
        history) are allowed for backward compatibility.
        """
        middleware = build_middleware(selected=["safe_echo"])
        origin = AIMessage(
            content="",
            tool_calls=[{"name": "canary", "args": {}, "id": "call_1", "type": "tool_call"}],
        )
        request = self._tool_call_request([origin], name="canary", call_id="call_1")

        self.assertIsNone(middleware._deny_unadvertised_tool_call(request))


class TestLlmConfigToolSelectorMiddlewareAsync(IsolatedAsyncioTestCase):
    """
    End-to-end enforcement test through the async path
    (awrap_model_call/awrap_tool_call), which is how neuro-san invokes agents.
    """

    async def test_deselected_tool_does_not_execute_in_agent_async(self):
        """
        End-to-end through create_agent: the selection model selects only safe_echo,
        the (scripted) main model nonetheless emits a tool call for the de-selected
        canary tool, and the executor must not run it.

        This is the advertise-only desync from GHSA-3xg4-wfwr-gc2g Finding 1:
        without enforcement, the executor runs every configured tool regardless
        of what the selector advertised.
        """
        canary_ran: List[bool] = []

        @tool
        def canary() -> str:
            """A sensitive tool that should not run when de-selected."""
            canary_ran.append(True)
            return "canary executed"

        middleware = build_middleware(selected=["safe_echo"])
        main_model = ToolCallingFakeModel(responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "canary", "args": {}, "id": "call_1", "type": "tool_call"}],
            ),
            AIMessage(content="done"),
        ])
        agent = create_agent(
            model=main_model,
            tools=[safe_echo, canary],
            middleware=[middleware],
        )

        result = await agent.ainvoke({"messages": [HumanMessage("please run the canary tool")]})

        self.assertEqual(canary_ran, [], "De-selected tool must not execute")

        tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0].status, "error")
        self.assertIn("was not among the tools selected", tool_messages[0].content)

        # The AIMessage that emitted the tool call carries the advertisement stamp.
        stamped = [message for message in result["messages"]
                   if isinstance(message, AIMessage) and message.tool_calls]
        self.assertEqual(stamped[0].response_metadata.get(ADVERTISED_TOOLS_KEY), ["safe_echo"])
