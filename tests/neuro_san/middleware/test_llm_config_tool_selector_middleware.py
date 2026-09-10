
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
from typing import Optional
from unittest import TestCase

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
                     sly_data: Optional[Dict[str, Any]] = None,
                     origin_str: Optional[str] = None,
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


class TestLlmConfigToolSelectorMiddleware(TestCase):
    """
    Unit tests for execution-time enforcement of tool selection.
    """

    def test_stamp_advertised_tools(self):
        """
        The advertised tool names are recorded per tool call id the model emitted.
        _stamp_advertised_tools() receives the request as already narrowed by tool
        selection, so its tools list models the narrowed (advertised) set.
        """
        middleware = build_middleware(selected=["safe_echo"])
        request = ModelRequest(
            model=ToolCallingFakeModel(responses=[]),
            messages=[HumanMessage("hi")],
            tools=[safe_echo],
        )
        response = ModelResponse(result=[
            AIMessage(
                content="",
                tool_calls=[{"name": "canary", "args": {}, "id": "call_1", "type": "tool_call"}],
            ),
        ])

        middleware._stamp_advertised_tools(request, response)

        self.assertEqual(middleware.advertised_tools, {"call_1": ["safe_echo"]})

    def test_stamp_records_dict_tool_names(self):
        """
        Provider-specific dict tools are recorded by name, whether the name is at
        the top level or nested in OpenAI function format.
        """
        middleware = build_middleware(selected=["safe_echo"])
        request = ModelRequest(
            model=ToolCallingFakeModel(responses=[]),
            messages=[HumanMessage("hi")],
            tools=[
                {"name": "top_level_tool"},
                {"type": "function", "function": {"name": "nested_tool"}},
            ],
        )
        response = ModelResponse(result=[
            AIMessage(
                content="",
                tool_calls=[{"name": "nested_tool", "args": {}, "id": "call_1", "type": "tool_call"}],
            ),
        ])

        middleware._stamp_advertised_tools(request, response)

        self.assertEqual(middleware.advertised_tools, {"call_1": ["top_level_tool", "nested_tool"]})

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

    def _tool_call_request(self, name: str, call_id: Optional[str]) -> ToolCallRequest:
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
