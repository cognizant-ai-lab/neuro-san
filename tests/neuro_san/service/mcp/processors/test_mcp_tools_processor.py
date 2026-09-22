
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
from typing import AsyncGenerator
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import json

from functools import partial
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from typing_extensions import override

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.mcp.processors.mcp_tools_processor import McpToolsProcessor


# These tests exercise deliberately-internal helpers directly; suppress
# protected-access warnings file-wide.
# pylint: disable=protected-access
class TestMcpToolsProcessor(IsolatedAsyncioTestCase):
    """
    Unit tests for McpToolsProcessor: tools/list advertises provider-safe tool names
    (with the network name carried as "title"), and tools/call maps an advertised
    name back to the network name that the authorizer and service table are keyed by.
    """

    NESTED_NAME: str = "deep/math_guy"
    NESTED_TOOL_NAME: str = "deep__math_guy"
    TOP_NAME: str = "math_guy"
    DESCRIPTION: str = "Does math"
    SCHEMA: Dict[str, Any] = {"type": "object"}

    @override
    def setUp(self) -> None:
        """
        Builds a processor over real storage holding one nested and one top-level MCP network,
        with mocked authorization, service, and request validation.
        """
        # Real storage and real networks: the processor reads is_mcp_tool() and
        # get_mcp_tool_name() off them, which is exactly what is under test.
        storage: AgentNetworkStorage = AgentNetworkStorage()

        self.nested: AgentNetwork = self.make_agent_network(self.NESTED_NAME)
        self.nested.set_as_mcp_tool(self.NESTED_TOOL_NAME)
        storage.add_agent_network(self.NESTED_NAME, self.nested)

        self.top: AgentNetwork = self.make_agent_network(self.TOP_NAME)
        self.top.set_as_mcp_tool(self.TOP_NAME)
        storage.add_agent_network(self.TOP_NAME, self.top)

        self.service: MagicMock = MagicMock()
        self.service.function = AsyncMock(return_value={"function": {"description": self.DESCRIPTION}})
        self.service.is_mcp_tool.return_value = True
        # 0.0 means "no timeout" to call_tool()
        self.service.get_request_timeout_seconds.return_value = 0.0
        self.service.streaming_chat = self.fake_streaming_chat

        self.service_provider: MagicMock = MagicMock()
        self.service_provider.get_service.return_value = self.service

        self.agent_policy: MagicMock = MagicMock()
        self.agent_policy.list_agents = AsyncMock(return_value=[self.NESTED_NAME, self.TOP_NAME])
        self.agent_policy.allow_agent = AsyncMock(return_value=(True, self.service_provider))

        validator: MagicMock = MagicMock()
        validator.get_request_schema.return_value = self.SCHEMA

        self.processor: McpToolsProcessor = McpToolsProcessor(
            MagicMock(), {StorageClass.PUBLIC: storage}, self.agent_policy, validator)

    def make_agent_network(self, network_name: str) -> AgentNetwork:
        """
        Builds a minimal AgentNetwork with a single front man.

        :param network_name: The network name to give it
        :return: An AgentNetwork that is not (yet) an MCP tool
        """
        config: Dict[str, Any] = {
            "tools": [
                {"name": "front", "function": {"description": "x"}}
            ]
        }
        return AgentNetwork(config, network_name)

    async def fake_streaming_chat(self, request_dict: Dict[str, Any],
                                  metadata: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stands in for AsyncAgentService.streaming_chat(), yielding one final answer.

        :param request_dict: The chat request; echoed back in the answer for assertions
        :param metadata: http-level request metadata; unused
        :return: An async generator of one AGENT_FRAMEWORK response
        """
        _ = metadata
        text: str = request_dict.get("user_message", {}).get("text", "")
        yield {"response": {"type": "AGENT_FRAMEWORK", "text": f"answer to {text}"}}

    @staticmethod
    def allow_only(allowed_name: str, service_provider: MagicMock,
                   agent_name: str, metadata: Dict[str, Any]) -> Tuple[bool, MagicMock]:
        """
        allow_agent() side effect that authorizes exactly one network.

        :param allowed_name: The only network name to authorize (bound with functools.partial)
        :param service_provider: The provider to return for every network (bound with functools.partial)
        :param agent_name: The network name being asked about
        :param metadata: http-level request metadata; unused
        :return: The (is_authorized, service_provider) tuple allow_agent() returns
        """
        _ = metadata
        return agent_name == allowed_name, service_provider

    @staticmethod
    def find_tool(tools: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
        """
        Finds the tools/list entry advertised under the given name.

        :param tools: The "tools" list from a tools/list result
        :param name: The advertised tool name to look for
        :return: The matching tool dictionary, or None
        """
        for tool in tools:
            if tool.get("name") == name:
                return tool
        return None

    async def test_list_tools_advertises_safe_name_with_title(self) -> None:
        """
        The nested network is listed under its provider-safe name with the network name as "title";
        the top-level network is listed under its own name with no "title".
        """
        result: Dict[str, Any] = await self.processor.list_tools(7, {})
        tools: List[Dict[str, Any]] = result["result"]["tools"]
        self.assertEqual(2, len(tools))

        nested_tool: Dict[str, Any] = self.find_tool(tools, self.NESTED_TOOL_NAME)
        self.assertIsNotNone(nested_tool)
        self.assertEqual(self.NESTED_NAME, nested_tool.get("title"))
        self.assertEqual(self.DESCRIPTION, nested_tool.get("description"))
        self.assertEqual(self.SCHEMA, nested_tool.get("inputSchema"))

        top_tool: Dict[str, Any] = self.find_tool(tools, self.TOP_NAME)
        self.assertIsNotNone(top_tool)
        self.assertNotIn("title", top_tool)

        # The raw network name must never leak out as a tool name.
        self.assertIsNone(self.find_tool(tools, self.NESTED_NAME))

    async def test_list_tools_authorizes_by_network_name(self) -> None:
        """
        Authorization is keyed by network name, not by the advertised tool name.
        """
        await self.processor.list_tools(7, {})
        asked_names: List[str] = []
        for call in self.agent_policy.allow_agent.await_args_list:
            asked_names.append(call.args[0])
        self.assertIn(self.NESTED_NAME, asked_names)
        self.assertNotIn(self.NESTED_TOOL_NAME, asked_names)

    async def test_list_tools_skips_unauthorized_network(self) -> None:
        """
        When the authorizer refuses a network, _get_tool_description() returns None
        and list_tools() must not append that None to the tools list.
        """
        self.agent_policy.allow_agent = AsyncMock(
            side_effect=partial(self.allow_only, self.TOP_NAME, self.service_provider))
        result: Dict[str, Any] = await self.processor.list_tools(7, {})
        tools: List[Dict[str, Any]] = result["result"]["tools"]
        self.assertEqual(1, len(tools))
        self.assertNotIn(None, tools)
        self.assertEqual(self.TOP_NAME, tools[0].get("name"))

    async def test_list_tools_falls_back_to_network_name_without_tool_name(self) -> None:
        """
        A network marked as an MCP tool without a tool name (older callers of set_as_mcp_tool)
        is advertised under its network name, with no "title".
        """
        # Bypass set_as_mcp_tool()'s own fallback to model a bare flag.
        self.top.mcp_tool_name = None
        result: Dict[str, Any] = await self.processor.list_tools(7, {})
        top_tool: Dict[str, Any] = self.find_tool(result["result"]["tools"], self.TOP_NAME)
        self.assertIsNotNone(top_tool)
        self.assertNotIn("title", top_tool)

    async def test_call_tool_resolves_safe_name_to_network_name(self) -> None:
        """
        A tools/call by the advertised name authorizes and dispatches by the network name,
        and the answer comes back.
        """
        result: Dict[str, Any] = await self.processor.call_tool(
            3, {}, self.NESTED_TOOL_NAME, {"type": "HUMAN", "text": "2+2"}, None, None, None)

        self.agent_policy.allow_agent.assert_awaited_once_with(self.NESTED_NAME, {})
        self.assertFalse(result["result"]["isError"])
        self.assertEqual("answer to 2+2", result["result"]["content"][0]["text"])

    async def test_call_tool_accepts_legacy_network_name(self) -> None:
        """
        The slash spelling still works for tools/call, so existing clients are not broken.
        """
        result: Dict[str, Any] = await self.processor.call_tool(
            3, {}, self.NESTED_NAME, {"type": "HUMAN", "text": "hi"}, None, None, None)
        self.agent_policy.allow_agent.assert_awaited_once_with(self.NESTED_NAME, {})
        self.assertFalse(result["result"]["isError"])

    async def test_call_tool_unknown_name_passes_through_to_error(self) -> None:
        """
        An unknown tool name is passed through unchanged and reported back to the client as-is.
        """
        self.agent_policy.allow_agent = AsyncMock(return_value=(True, None))
        result: Dict[str, Any] = await self.processor.call_tool(
            3, {}, "no_such_tool", {"type": "HUMAN", "text": "hi"}, None, None, None)
        self.agent_policy.allow_agent.assert_awaited_once_with("no_such_tool", {})
        self.assertIn("no_such_tool", json.dumps(result))

    async def test_call_tool_not_found_error_names_tool_as_called(self) -> None:
        """
        When the advertised name differs from the network name, a "not found" error
        names the tool the way the client called it, not the network it mapped to.
        """
        self.agent_policy.allow_agent = AsyncMock(return_value=(True, None))
        result: Dict[str, Any] = await self.processor.call_tool(
            3, {}, self.NESTED_TOOL_NAME, {"type": "HUMAN", "text": "hi"}, None, None, None)
        self.agent_policy.allow_agent.assert_awaited_once_with(self.NESTED_NAME, {})
        text: str = json.dumps(result)
        self.assertIn(f"Tool not found: {self.NESTED_TOOL_NAME}", text)
        self.assertNotIn(self.NESTED_NAME, text)

    async def test_call_tool_not_authorized_error_names_tool_as_called(self) -> None:
        """
        Same for the "not authorized" error.
        """
        self.agent_policy.allow_agent = AsyncMock(return_value=(False, self.service_provider))
        result: Dict[str, Any] = await self.processor.call_tool(
            3, {}, self.NESTED_TOOL_NAME, {"type": "HUMAN", "text": "hi"}, None, None, None)
        text: str = json.dumps(result)
        self.assertIn(f"Tool not authorized: {self.NESTED_TOOL_NAME}", text)
        self.assertNotIn(self.NESTED_NAME, text)

    async def test_call_tool_not_available_error_names_tool_as_called(self) -> None:
        """
        Same for the "not available as MCP tool" error.
        """
        self.service.is_mcp_tool.return_value = False
        result: Dict[str, Any] = await self.processor.call_tool(
            3, {}, self.NESTED_TOOL_NAME, {"type": "HUMAN", "text": "hi"}, None, None, None)
        text: str = json.dumps(result)
        self.assertIn(f"Service not available as MCP tool: {self.NESTED_TOOL_NAME}", text)
        self.assertNotIn(self.NESTED_NAME, text)

    def test_resolve_network_name_maps_safe_name_back(self) -> None:
        """
        The advertised name resolves to the network name it stands for.
        """
        self.assertEqual(self.NESTED_NAME, self.processor._resolve_network_name(self.NESTED_TOOL_NAME))

    def test_resolve_network_name_passes_other_names_through(self) -> None:
        """
        Top-level names, the legacy slash spelling, and unknown names come back unchanged.
        """
        self.assertEqual(self.TOP_NAME, self.processor._resolve_network_name(self.TOP_NAME))
        self.assertEqual(self.NESTED_NAME, self.processor._resolve_network_name(self.NESTED_NAME))
        self.assertEqual("no_such_tool", self.processor._resolve_network_name("no_such_tool"))

    def test_resolve_network_name_ignores_non_mcp_networks(self) -> None:
        """
        A network that is not an MCP tool never claims a tool name, even if its stale
        mcp_tool_name attribute would match.
        """
        # clear_mcp_tool() would also drop the name; flip only the flag so the
        # stale name is really there to be ignored.
        self.nested.is_mcp_network = False
        self.assertEqual(self.NESTED_TOOL_NAME, self.processor._resolve_network_name(self.NESTED_TOOL_NAME))
