
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
from typing import Dict
from typing import List

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from langchain_core.tools import BaseTool
from langchain_core.tools import StructuredTool

from neuro_san.internals.run_context.langchain.tools.exposed_tool_names import ExposedToolNames
from neuro_san.internals.run_context.langchain.tools.mcp_tool_creator import McpToolCreator
from neuro_san.message.types.agent_message import AgentMessage


class TestMcpToolCreator(IsolatedAsyncioTestCase):
    """
    Unit tests for McpToolCreator: what reaches the adapter for one MCP server,
    and the policy the creator applies on top of what the adapter returns.
    """

    ADAPTER_PATH: str = "neuro_san.internals.run_context.langchain.tools.mcp_tool_creator.LangChainMcpAdapter"
    AGENT_LOCATION: str = "agent 'researcher' of agent network 'deep/math_guy'"
    SERVER_URL: str = "https://mcp.example.com/mcp"
    HEADERS: Dict[str, str] = {"Authorization": "Bearer token"}

    @staticmethod
    def make_named_tool(name: str) -> MagicMock:
        """
        Builds a StructuredTool-shaped mock with the given name.

        :param name: The exposed tool name
        :return: A StructuredTool-shaped mock carrying that name
        """
        tool = MagicMock(spec=StructuredTool)
        tool.name = name
        return tool

    def make_creator(self, with_headers: bool = True, allowed_tools: List[str] = None) -> McpToolCreator:
        """
        Builds a creator with an empty ExposedToolNames record.

        :param with_headers: True to give sly_data headers for SERVER_URL, False for empty sly_data
        :param allowed_tools: The allow list to build the creator with, None for none
        :return: An McpToolCreator over mocked collaborators
        """
        sly_data: Dict[str, Any] = {}
        if with_headers:
            sly_data = {"http_headers": {self.SERVER_URL: self.HEADERS}}
        tool_caller = MagicMock()
        tool_caller.get_sly_data = MagicMock(return_value=sly_data)

        journal = MagicMock()
        journal.write_message = AsyncMock()

        exposed_tool_names: ExposedToolNames = ExposedToolNames(journal, self.AGENT_LOCATION)
        return McpToolCreator(tool_caller, MagicMock(), journal, self.AGENT_LOCATION, exposed_tool_names,
                              allowed_tools)

    @staticmethod
    def prepare_adapter(mock_adapter_class: MagicMock, tools: List[BaseTool],
                        unmatched: List[str] = None) -> MagicMock:
        """
        Configures the patched adapter class's instance for a test.

        :param mock_adapter_class: The patched LangChainMcpAdapter class
        :param tools: What get_mcp_tools() should return
        :param unmatched: What get_unmatched_allowed_tools() should return
        :return: The adapter instance mock
        """
        mock_adapter: MagicMock = mock_adapter_class.return_value
        mock_adapter.get_mcp_tools = AsyncMock(return_value=tools)
        mock_adapter.get_unmatched_allowed_tools = MagicMock(return_value=unmatched or [])
        return mock_adapter

    @patch(ADAPTER_PATH)
    async def test_allow_list_and_headers_reach_the_adapter(self, mock_adapter_class: MagicMock) -> None:
        """
        The creator hands the adapter the URL, the allow list it was built with
        and the headers sly_data holds for that URL, and the adapter is told
        where the request comes from so its warnings can say so.

        :param mock_adapter_class: Patched LangChainMcpAdapter class.
        """
        tool: MagicMock = self.make_named_tool("tool_1")
        mock_adapter: MagicMock = self.prepare_adapter(mock_adapter_class, [tool])
        creator: McpToolCreator = self.make_creator(allowed_tools=["tool_1"])

        result: List[BaseTool] = await creator.create_tool(self.SERVER_URL)

        self.assertEqual(result, [tool])
        mock_adapter_class.assert_called_once_with(self.AGENT_LOCATION)
        mock_adapter.get_mcp_tools.assert_awaited_once_with(self.SERVER_URL, ["tool_1"], self.HEADERS)
        creator.journal.write_message.assert_not_awaited()

    @patch(ADAPTER_PATH)
    async def test_no_allow_list_or_headers_passes_none_for_both(self, mock_adapter_class: MagicMock) -> None:
        """
        A creator built without an allow list, for an agent whose sly_data holds no
        headers, hands the adapter None for both, so the adapter's own defaults apply.

        :param mock_adapter_class: Patched LangChainMcpAdapter class.
        """
        mock_adapter: MagicMock = self.prepare_adapter(mock_adapter_class, [self.make_named_tool("tool_1")])
        creator: McpToolCreator = self.make_creator(with_headers=False)

        await creator.create_tool(self.SERVER_URL)

        mock_adapter.get_mcp_tools.assert_awaited_once_with(self.SERVER_URL, None, None)

    @patch(ADAPTER_PATH)
    async def test_without_allow_list_the_adapter_decides(self, mock_adapter_class: MagicMock) -> None:
        """
        A server referenced by URL alone lets the adapter decide the allow list
        (None here, the MCP servers info file may still supply one), while the
        headers for that URL still apply.

        :param mock_adapter_class: Patched LangChainMcpAdapter class.
        """
        mock_adapter: MagicMock = self.prepare_adapter(mock_adapter_class, [self.make_named_tool("tool_1")])
        creator: McpToolCreator = self.make_creator()

        await creator.create_tool(self.SERVER_URL)

        mock_adapter.get_mcp_tools.assert_awaited_once_with(self.SERVER_URL, None, self.HEADERS)

    @patch(ADAPTER_PATH)
    async def test_tool_whose_name_is_already_exposed_is_skipped(self, mock_adapter_class: MagicMock) -> None:
        """
        A tool whose exposed name an earlier tool of the agent already uses is
        dropped with a journal message that says where to fix it; the others
        are kept in order.

        :param mock_adapter_class: Patched LangChainMcpAdapter class.
        """
        taken: MagicMock = self.make_named_tool("a__b")
        other: MagicMock = self.make_named_tool("other_tool")
        self.prepare_adapter(mock_adapter_class, [taken, other])
        creator: McpToolCreator = self.make_creator()
        await creator.exposed_tool_names.remember(self.make_named_tool("a__b"))

        result: List[BaseTool] = await creator.create_tool(self.SERVER_URL)

        self.assertEqual(result, [other])
        creator.journal.write_message.assert_awaited_once()
        reported: AgentMessage = creator.journal.write_message.await_args.args[0]
        expected_start: str = f"{self.AGENT_LOCATION}: MCP tool 'a__b' from {self.SERVER_URL}"
        self.assertTrue(reported.content.startswith(expected_start), reported.content)
        self.assertIn("skipping it", reported.content)
        self.assertIn("hocon file", reported.content)

    @patch(ADAPTER_PATH)
    async def test_unmatched_allow_list_entries_are_reported(self, mock_adapter_class: MagicMock) -> None:
        """
        Allow-list entries the adapter could match to no tool are reported as
        "cannot be found", and the matched tools are still returned.

        :param mock_adapter_class: Patched LangChainMcpAdapter class.
        """
        tool: MagicMock = self.make_named_tool("tool_1")
        self.prepare_adapter(mock_adapter_class, [tool], unmatched=["nope"])
        creator: McpToolCreator = self.make_creator(allowed_tools=["tool_1", "nope"])

        result: List[BaseTool] = await creator.create_tool(self.SERVER_URL)

        self.assertEqual(result, [tool])
        creator.journal.write_message.assert_awaited_once()
        reported: AgentMessage = creator.journal.write_message.await_args.args[0]
        self.assertTrue(reported.content.startswith(f"{self.AGENT_LOCATION}: "), reported.content)
        self.assertIn("cannot be found", reported.content)
        self.assertIn("nope", reported.content)

    @patch(ADAPTER_PATH)
    async def test_unreachable_server_is_reported_and_yields_none(self, mock_adapter_class: MagicMock) -> None:
        """
        The MCP client raises an ExceptionGroup when the server cannot be
        reached. The creator reports it, naming the agent and the URL, and
        contributes no tools.

        :param mock_adapter_class: Patched LangChainMcpAdapter class.
        """
        mock_adapter: MagicMock = mock_adapter_class.return_value
        mock_adapter.get_mcp_tools = AsyncMock(side_effect=ExceptionGroup("boom", [ConnectionError("refused")]))
        creator: McpToolCreator = self.make_creator()

        result: List[BaseTool] = await creator.create_tool(self.SERVER_URL)

        self.assertIsNone(result)
        creator.journal.write_message.assert_awaited_once()
        reported: AgentMessage = creator.journal.write_message.await_args.args[0]
        self.assertTrue(reported.content.startswith(f"{self.AGENT_LOCATION}: the URL {self.SERVER_URL}"),
                        reported.content)
        self.assertIn("unreachable", reported.content)
