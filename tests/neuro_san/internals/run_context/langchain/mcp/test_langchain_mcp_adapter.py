
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
from typing import Optional

import os

from logging import ERROR
from logging import INFO
from logging import WARNING

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp.types import CallToolResult
from mcp.types import TextContent
from mcp.types import Tool as McpTool
from typing_extensions import override

from neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter import LangChainMcpAdapter


# These tests reset the adapter's class-level servers-info cache directly.
# pylint: disable=protected-access
# One test class per source class is the repo convention, so the test count grows with the class.
# pylint: disable=too-many-public-methods
class TestLangChainMcpAdapter(IsolatedAsyncioTestCase):
    """
    Unit tests for LangChainMcpAdapter: fetching tools from an MCP server, applying
    the allow list in either spelling, renaming provider-unsafe tool names, and
    wrapping tool errors so they reach the LLM as text instead of exceptions.
    """

    SERVER_URL: str = "https://mcp.example.com/mcp"
    # Logger names as the code derives them from the class names.
    ADAPTER_LOGGER: str = "LangChainMcpAdapter"
    HANDLER_LOGGER: str = "McpToolErrorHandler"

    @override
    def setUp(self) -> None:
        """
        Clears the adapter's shared servers-info cache and builds a fresh adapter
        and a plain mock tool for each test.
        """
        LangChainMcpAdapter._mcp_servers_info = None
        self.adapter: LangChainMcpAdapter = LangChainMcpAdapter()
        self.mock_mcp_tool: MagicMock = self._make_tool("test_tool")

    @override
    def tearDown(self) -> None:
        """
        Clears the shared servers-info cache so no test leaks it into the next.
        """
        LangChainMcpAdapter._mcp_servers_info = None

    @staticmethod
    def _make_tool(name: Optional[str]) -> MagicMock:
        """
        Builds a StructuredTool-shaped mock carrying the given name.

        The name must be assigned after construction: MagicMock's name= kwarg
        only sets the mock's repr, and with spec=StructuredTool reading .name
        without an explicit assignment raises AttributeError.

        :param name: The tool name the fake MCP server advertises; None models a
                     tool advertised without a name.
        :return: A MagicMock with .name and .tags set like a fresh MCP tool.
        """
        tool: MagicMock = MagicMock(spec=StructuredTool)
        tool.name = name
        tool.tags = []
        return tool

    @staticmethod
    def _make_tools(names: List[str]) -> List[MagicMock]:
        """
        Builds one StructuredTool-shaped mock per name, in order.

        Renaming mutates a mock's .name in place, so a test that calls
        get_mcp_tools() more than once needs a fresh list for each call.

        :param names: The tool names the fake MCP server advertises.
        :return: The mocks, in the same order as names.
        """
        tools: List[MagicMock] = []
        for name in names:
            tools.append(TestLangChainMcpAdapter._make_tool(name))
        return tools

    @staticmethod
    def _make_real_tool(name: str, coroutine: AsyncMock) -> StructuredTool:
        """
        Builds a real StructuredTool the way langchain_mcp_adapters shapes them,
        with a caller-supplied coroutine standing in for the MCP call.

        :param name: The tool name.
        :param coroutine: The AsyncMock invoked in place of the MCP session call.
        :return: A StructuredTool with a JSON-schema args_schema and
                 content_and_artifact response format.
        """
        return StructuredTool(
            name=name,
            description="test tool",
            args_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            coroutine=coroutine,
            response_format="content_and_artifact",
        )

    def test_init(self) -> None:
        """
        A fresh adapter has an empty allow list, no unmatched entries and a logger.
        """
        self.assertEqual(self.adapter.client_allowed_tools, [])
        self.assertEqual(self.adapter.unmatched_allowed_tools, [])
        self.assertIsNotNone(self.adapter.logger)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_basic(self, mock_client_class: MagicMock) -> None:
        """
        The tools the client returns come back tagged, and the client is built
        and queried exactly once.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[self.mock_mcp_tool])

        tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "test_tool")
        self.assertIn("langchain_tool", tools[0].tags)
        mock_client_class.assert_called_once()
        mock_client.get_tools.assert_called_once()

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_allowed_tools_param(self, mock_client_class: MagicMock) -> None:
        """
        An allow list passed in keeps only the tools it names and is recorded on
        the adapter as written.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=self._make_tools(["allowed_tool", "disallowed_tool"]))

        allowed_tools: List[str] = ["allowed_tool"]
        tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL, allowed_tools=allowed_tools)

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "allowed_tool")
        self.assertEqual(self.adapter.client_allowed_tools, allowed_tools)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpServersInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_config_allowed_tools(
            self, mock_client_class: MagicMock, mock_restorer_class: MagicMock) -> None:
        """
        Without an allow list passed in, the "tools" list from the MCP servers
        info for this server is used.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param mock_restorer_class: Patched McpServersInfoRestorer class.
        """
        mock_restorer: MagicMock = mock_restorer_class.return_value
        mock_restorer.restore.return_value = {self.SERVER_URL: {"tools": ["config_tool"]}}
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=self._make_tools(["config_tool", "other_tool"]))

        tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "config_tool")

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpServersInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_headers_param(
            self, mock_client_class: MagicMock, mock_restorer_class: MagicMock) -> None:
        """
        Headers passed in are handed to the MCP client for this server.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param mock_restorer_class: Patched McpServersInfoRestorer class.
        """
        headers: Dict[str, str] = {"Authorization": "Bearer custom_token"}
        mock_restorer: MagicMock = mock_restorer_class.return_value
        mock_restorer.restore.return_value = {}
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await self.adapter.get_mcp_tools(self.SERVER_URL, headers=headers)

        client_config: Dict[str, Any] = mock_client_class.call_args[0][0]
        self.assertIn("headers", client_config["server"])
        self.assertEqual(client_config["server"]["headers"]["Authorization"], "Bearer custom_token")

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpServersInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_config_headers(
            self, mock_client_class: MagicMock, mock_restorer_class: MagicMock) -> None:
        """
        Without headers passed in, the "http_headers" from the MCP servers info
        for this server are handed to the MCP client.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param mock_restorer_class: Patched McpServersInfoRestorer class.
        """
        mock_restorer: MagicMock = mock_restorer_class.return_value
        mock_restorer.restore.return_value = {
            self.SERVER_URL: {"http_headers": {"Authorization": "Bearer config_token"}}
        }
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await self.adapter.get_mcp_tools(self.SERVER_URL)

        client_config: Dict[str, Any] = mock_client_class.call_args[0][0]
        self.assertIn("headers", client_config["server"])
        self.assertEqual(client_config["server"]["headers"]["Authorization"], "Bearer config_token")

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_invalid_headers_type(self, mock_client_class: MagicMock) -> None:
        """
        Headers in the servers info that are not a dictionary are reported in the
        log, and the tools are still fetched from the server.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        LangChainMcpAdapter._mcp_servers_info = {self.SERVER_URL: {"http_headers": "invalid_string_not_dict"}}
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        with self.assertLogs(self.ADAPTER_LOGGER, level=ERROR) as captured:
            await self.adapter.get_mcp_tools(self.SERVER_URL)

        self.assertIn("must be a dictionary", "\n".join(captured.output))
        mock_client.get_tools.assert_awaited_once()

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_adds_langchain_tool_tags(self, mock_client_class: MagicMock) -> None:
        """
        Every returned tool carries the "langchain_tool" tag the journal callback
        looks for.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        # Names are assigned explicitly: MagicMock(name=...) only sets the repr,
        # and the adapter reads tool.name on every tool to check it is safe.
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=self._make_tools(["tool0", "tool1", "tool2"]))

        result: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)

        self.assertEqual(len(result), 3)
        for tool in result:
            self.assertIn("langchain_tool", tool.tags)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_wraps_tool_errors(self, mock_client_class: MagicMock) -> None:
        """
        A tool whose MCP call raises (e.g. an HTTP 504 from a gateway timeout)
        returns a concise "Error: ..." tool output instead of propagating the
        exception and aborting the whole agent chain. The full traceback stays in
        the server log. See https://github.com/cognizant-ai-lab/neuro-san/issues/1097

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        tool: StructuredTool = self._make_real_tool("wolfram", AsyncMock(
            side_effect=RuntimeError("Server error '504 Gateway Time-out' for url 'https://mcp.example.com/mcp'")))
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[tool])

        # McpToolErrorHandler logs through a SensitiveLogger that reads
        # LEAF_LOG_SENSITIVE once, when the handler is built inside
        # get_mcp_tools(), so pin it here to keep the log assertion below
        # independent of the environment.
        with patch.dict(os.environ, {"LEAF_LOG_SENSITIVE": "true"}):
            tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)

            # Invoking the tool does not raise; the LLM sees a concise error message.
            with self.assertLogs(self.HANDLER_LOGGER, level=ERROR) as captured:
                result: str = await tools[0].ainvoke({"query": "toss a coin 10 million times"})

        self.assertEqual(
            result,
            "Error: RuntimeError: Server error '504 Gateway Time-out' for url 'https://mcp.example.com/mcp'")
        # The full traceback is preserved in the server log for debugging.
        self.assertIn("RuntimeError", "\n".join(captured.output))

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_unwraps_exception_groups(self, mock_client_class: MagicMock) -> None:
        """
        When the MCP transport fails at call time, anyio raises an ExceptionGroup
        whose str() is just "unhandled errors in a TaskGroup (1 sub-exception)".
        The tool output surfaces the underlying cause instead of that summary.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        tool: StructuredTool = self._make_real_tool("wolfram", AsyncMock(
            side_effect=ExceptionGroup(
                "unhandled errors in a TaskGroup",
                [ConnectionError("All connection attempts failed")])))
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[tool])

        tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)
        result: str = await tools[0].ainvoke({"query": "toss a coin 10 million times"})

        # The real cause is in the output, not just the TaskGroup summary.
        self.assertIn("ConnectionError: All connection attempts failed", result)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_wrapped_tools_pass_through_results(self, mock_client_class: MagicMock) -> None:
        """
        The error wrapping does not disturb normal (non-raising) tool results.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        tool: StructuredTool = self._make_real_tool("wolfram", AsyncMock(return_value=("42", None)))
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[tool])

        tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)
        result: str = await tools[0].ainvoke({"query": "6 times 7"})

        self.assertEqual(result, "42")

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpServersInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_proceeds_when_restore_raises_value_error(
            self, mock_client_class: MagicMock, mock_restorer_class: MagicMock) -> None:
        """
        A malformed servers info file (restore() raising ValueError) neither hangs
        nor propagates: get_mcp_tools logs a warning naming the cause and proceeds
        with an empty servers info dict.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param mock_restorer_class: Patched McpServersInfoRestorer class.
        """
        mock_restorer: MagicMock = mock_restorer_class.return_value
        mock_restorer.restore.side_effect = ValueError(
            'There was an error loading MCP servers info file "mcp_info.hocon".\n'
            "Underlying error (ConfigSubstitutionException): "
            "Cannot resolve variable ${YDC_API_KEY} (line: 68, col: 39)")
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[self.mock_mcp_tool])

        with self.assertLogs(self.ADAPTER_LOGGER, level=WARNING) as captured:
            tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)

        # The tool fetch still completes: the load failure does not propagate.
        self.assertEqual(len(tools), 1)
        # Fallback to the empty dict so subsequent lookups do not blow up.
        self.assertEqual(LangChainMcpAdapter._mcp_servers_info, {})
        # The real underlying cause is surfaced in the log so users can diagnose.
        self.assertIn("Cannot resolve variable ${YDC_API_KEY}", "\n".join(captured.output))

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_renames_only_unsafe_names(self, mock_client_class: MagicMock) -> None:
        """
        A server tool named with a "/" is exposed to the LLM under the
        provider-safe "__" spelling and the rename is logged at INFO, while a
        tool whose name is already safe is returned unchanged with no log line.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=self._make_tools(["basic/music_nerd_pro", "Safe_tool-1"]))

        # The routine rename is INFO, so capture from that level.
        with self.assertLogs(self.ADAPTER_LOGGER, level=INFO) as captured:
            tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)
        output: str = "\n".join(captured.output)

        self.assertEqual(len(tools), 2)
        self.assertEqual(tools[0].name, "basic__music_nerd_pro")
        self.assertEqual(tools[1].name, "Safe_tool-1")
        self.assertIn("langchain_tool", tools[0].tags)
        self.assertIn("tool 'basic/music_nerd_pro' renamed to 'basic__music_nerd_pro'", output)
        # The operator must be told the server still sees the original name.
        self.assertIn("still called with the original name", output)
        self.assertNotIn("'Safe_tool-1' renamed", output)
        self.assertNotIn("match no tool", output)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_allow_list_accepts_either_spelling(self, mock_client_class: MagicMock) -> None:
        """
        An allow-list entry keeps the matching "/" server tool whether written in
        the server's original spelling or in the provider-safe spelling seen in
        logs and thinking output. An entry matching nothing yields no tools and
        logs a warning naming the entry and the tools the server does offer,
        instead of dropping it silently.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        server_names: List[str] = ["basic/music_nerd_pro", "other_tool"]
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(side_effect=[
            self._make_tools(server_names),
            self._make_tools(server_names),
            self._make_tools(server_names),
        ])

        with self.assertLogs(self.ADAPTER_LOGGER, level=INFO) as matched:
            original_spelling: List[StructuredTool] = await self.adapter.get_mcp_tools(
                self.SERVER_URL, allowed_tools=["basic/music_nerd_pro"])
            safe_spelling: List[StructuredTool] = await self.adapter.get_mcp_tools(
                self.SERVER_URL, allowed_tools=["basic__music_nerd_pro"])
        self.assertNotIn("match no tool", "\n".join(matched.output))

        with self.assertLogs(self.ADAPTER_LOGGER, level=WARNING) as unmatched_log:
            unmatched: List[StructuredTool] = await self.adapter.get_mcp_tools(
                self.SERVER_URL, allowed_tools=["nope"])
        output: str = "\n".join(unmatched_log.output)

        self.assertEqual(len(original_spelling), 1)
        self.assertEqual(original_spelling[0].name, "basic__music_nerd_pro")
        self.assertEqual(len(safe_spelling), 1)
        self.assertEqual(safe_spelling[0].name, "basic__music_nerd_pro")
        self.assertEqual(len(unmatched), 0)
        self.assertIn("match no tool on the server", output)
        self.assertIn("nope", output)
        self.assertIn("basic/music_nerd_pro", output)
        self.assertIn("other_tool", output)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_allow_list_exact_spelling_selects_one_tool(
            self, mock_client_class: MagicMock) -> None:
        """
        When a server offers both "a/b" and "a__b", an allow list naming "a/b"
        keeps exactly the "a/b" tool (then renamed) and one naming "a__b" keeps
        exactly the literal "a__b" tool. Neither case is a collision, so nothing
        is skipped and the author never silently gets the tool they did not name.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        first_slash: MagicMock = self._make_tool("a/b")
        first_safe: MagicMock = self._make_tool("a__b")
        second_slash: MagicMock = self._make_tool("a/b")
        second_safe: MagicMock = self._make_tool("a__b")
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(side_effect=[[first_slash, first_safe], [second_slash, second_safe]])

        # The first call renames "a/b", so there is at least one INFO line to capture.
        with self.assertLogs(self.ADAPTER_LOGGER, level=INFO) as captured:
            by_slash: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL, allowed_tools=["a/b"])
            by_safe: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL, allowed_tools=["a__b"])
        output: str = "\n".join(captured.output)

        self.assertEqual(len(by_slash), 1)
        # Identity, not just name: the "a/b" tool the author asked for is the survivor.
        self.assertIs(by_slash[0], first_slash)
        self.assertEqual(by_slash[0].name, "a__b")
        self.assertEqual(len(by_safe), 1)
        self.assertIs(by_safe[0], second_safe)
        self.assertEqual(by_safe[0].name, "a__b")
        self.assertNotIn("skipping it", output)
        self.assertNotIn("match no tool", output)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_skips_colliding_tools(self, mock_client_class: MagicMock) -> None:
        """
        Without an allow list, two tools mapping to one safe name are a collision:
        the tool needing no rename wins even when listed second ("a/b" vs "a__b"),
        and when both need renaming the first one listed wins ("a.b" vs "a b").
        The loser is skipped with a warning either way.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        slash_tool: MagicMock = self._make_tool("a/b")
        safe_tool: MagicMock = self._make_tool("a__b")
        dot_tool: MagicMock = self._make_tool("a.b")
        space_tool: MagicMock = self._make_tool("a b")
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(side_effect=[[slash_tool, safe_tool], [dot_tool, space_tool]])

        with self.assertLogs(self.ADAPTER_LOGGER, level=WARNING) as captured:
            safe_wins: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)
            first_wins: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)
        output: str = "\n".join(captured.output)

        self.assertEqual(len(safe_wins), 1)
        # Identity, not just name: the literal "a__b" tool is the survivor.
        self.assertIs(safe_wins[0], safe_tool)
        self.assertEqual(safe_wins[0].name, "a__b")
        self.assertIn("tool 'a/b' would be renamed to 'a__b'", output)
        self.assertIn("skipping it", output)
        self.assertEqual(len(first_wins), 1)
        self.assertIs(first_wins[0], dot_tool)
        self.assertEqual(first_wins[0].name, "a_b")
        self.assertIn("tool 'a b' would be renamed to 'a_b'", output)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_warns_when_renamed_name_exceeds_soft_limit(
            self, mock_client_class: MagicMock) -> None:
        """
        A rename that pushes a name past the 64-character OpenAI cap is kept
        (Anthropic and local providers accept it) but a warning is logged.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        # 34 + "/" + 34 = 69 chars originally; "__" makes the safe name 70 chars.
        original_name: str = ("a" * 34) + "/" + ("b" * 34)
        expected_name: str = ("a" * 34) + "__" + ("b" * 34)
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[self._make_tool(original_name)])

        with self.assertLogs(self.ADAPTER_LOGGER, level=WARNING) as captured:
            tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)
        output: str = "\n".join(captured.output)

        self.assertEqual(len(tools), 1)
        self.assertEqual(len(expected_name), 70)
        self.assertEqual(tools[0].name, expected_name)
        self.assertIn("over the 64-character OpenAI tool-name cap", output)
        self.assertIn("is 70 characters long", output)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_renames_real_tool_and_still_calls_server_with_original_name(
            self, mock_client_class: MagicMock) -> None:
        """
        On a real StructuredTool built by langchain_mcp_adapters, the rename is
        accepted by the model, the renamed tool can be invoked, and the MCP
        session is still asked for the original name, because the coroutine
        closed over the original mcp.types.Tool.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        session: MagicMock = MagicMock()
        session.call_tool = AsyncMock(return_value=CallToolResult(content=[TextContent(type="text", text="pong")]))
        mcp_tool: McpTool = McpTool(
            name="deep/echo_guy",
            description="echoes",
            inputSchema={"type": "object", "properties": {"user_message": {"type": "string"}},
                         "required": ["user_message"]})
        real_tool: StructuredTool = convert_mcp_tool_to_langchain_tool(session, mcp_tool)
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[real_tool])

        tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)
        result: str = await tools[0].ainvoke({"user_message": "ping"})

        self.assertIs(tools[0], real_tool)
        self.assertEqual(real_tool.name, "deep__echo_guy")
        self.assertEqual(result, "pong")
        # The first positional argument of ClientSession.call_tool() is the tool name.
        self.assertEqual(session.call_tool.await_args.args[0], "deep/echo_guy")

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_records_unmatched_allow_list_entries(self, mock_client_class: MagicMock) -> None:
        """
        unmatched_allowed_tools holds exactly the allow-list entries that matched
        no advertised tool in either spelling, so BaseToolFactory can report them
        instead of comparing the entries with the renamed tools. It is reset on
        every call and empty without an allow list.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        server_names: List[str] = ["basic/music_nerd_pro", "other_tool"]
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(side_effect=[
            self._make_tools(server_names),
            self._make_tools(server_names),
            self._make_tools(server_names),
        ])

        with self.assertLogs(self.ADAPTER_LOGGER, level=WARNING) as captured:
            await self.adapter.get_mcp_tools(self.SERVER_URL, allowed_tools=["basic/music_nerd_pro", "nope"])
        self.assertEqual(self.adapter.unmatched_allowed_tools, ["nope"])
        self.assertIn("nope", "\n".join(captured.output))

        await self.adapter.get_mcp_tools(self.SERVER_URL, allowed_tools=["basic__music_nerd_pro", "other_tool"])
        self.assertEqual(self.adapter.unmatched_allowed_tools, [])

        await self.adapter.get_mcp_tools(self.SERVER_URL)
        self.assertEqual(self.adapter.unmatched_allowed_tools, [])

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_allow_listed_pair_that_collides_keeps_the_first(
            self, mock_client_class: MagicMock) -> None:
        """
        Naming both "a.b" and "a b" in the allow list does not exempt them from
        collision handling: both rename to "a_b", the first one listed is kept
        and the second is skipped with a warning.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        dot_tool: MagicMock = self._make_tool("a.b")
        space_tool: MagicMock = self._make_tool("a b")
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[dot_tool, space_tool])

        with self.assertLogs(self.ADAPTER_LOGGER, level=WARNING) as captured:
            tools: List[StructuredTool] = await self.adapter.get_mcp_tools(
                self.SERVER_URL, allowed_tools=["a.b", "a b"])

        self.assertEqual(len(tools), 1)
        self.assertIs(tools[0], dot_tool)
        self.assertEqual(tools[0].name, "a_b")
        self.assertIn("tool 'a b' would be renamed to 'a_b'", "\n".join(captured.output))
        self.assertEqual(self.adapter.unmatched_allowed_tools, [])

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpServersInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_config_allow_list_accepts_safe_spelling(
            self, mock_client_class: MagicMock, mock_restorer_class: MagicMock) -> None:
        """
        An allow list taken from the MCP servers info file goes through the same
        either-spelling matching as one passed in: a provider-safe entry selects
        the "/" tool the server advertises, which is then renamed.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param mock_restorer_class: Patched McpServersInfoRestorer class.
        """
        mock_restorer: MagicMock = mock_restorer_class.return_value
        mock_restorer.restore.return_value = {self.SERVER_URL: {"tools": ["basic__music_nerd_pro"]}}
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=self._make_tools(["basic/music_nerd_pro", "other_tool"]))

        tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "basic__music_nerd_pro")
        self.assertEqual(self.adapter.unmatched_allowed_tools, [])

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_allow_list_against_empty_server_warns(self, mock_client_class: MagicMock) -> None:
        """
        A server that advertises nothing leaves every allow-list entry unmatched:
        no tools come back, and the warning shows the empty server list.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        with self.assertLogs(self.ADAPTER_LOGGER, level=WARNING) as captured:
            tools: List[StructuredTool] = await self.adapter.get_mcp_tools(
                self.SERVER_URL, allowed_tools=["some_tool"])

        self.assertEqual(tools, [])
        self.assertEqual(self.adapter.unmatched_allowed_tools, ["some_tool"])
        self.assertIn("Available tools: []", "\n".join(captured.output))

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_warns_when_renamed_name_exceeds_hard_limit(
            self, mock_client_class: MagicMock) -> None:
        """
        A rename that pushes a name past the 128-character cap is still kept, but
        the warning names that cap rather than only OpenAI's 64.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        original_name: str = ("a" * 100) + "/" + ("b" * 100)
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[self._make_tool(original_name)])

        with self.assertLogs(self.ADAPTER_LOGGER, level=WARNING) as captured:
            tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)
        output: str = "\n".join(captured.output)

        self.assertEqual(len(tools), 1)
        self.assertEqual(len(tools[0].name), 202)
        self.assertIn("over the 128-character tool-name cap", output)
        self.assertIn("is 202 characters long", output)
        self.assertNotIn("over the 64-character OpenAI tool-name cap", output)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_skips_duplicate_safe_names(self, mock_client_class: MagicMock) -> None:
        """
        A server that advertises one already-safe name twice yields that tool once:
        the first is kept, the duplicate is skipped with a warning, and unrelated
        tools are unaffected.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        first: MagicMock = self._make_tool("search")
        duplicate: MagicMock = self._make_tool("search")
        other: MagicMock = self._make_tool("other_tool")
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[first, duplicate, other])

        with self.assertLogs(self.ADAPTER_LOGGER, level=WARNING) as captured:
            tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)

        self.assertEqual(len(tools), 2)
        self.assertIs(tools[0], first)
        self.assertIs(tools[1], other)
        self.assertIn("tool 'search' is advertised more than once", "\n".join(captured.output))

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_warns_when_unchanged_name_exceeds_soft_limit(
            self, mock_client_class: MagicMock) -> None:
        """
        A name that needs no rename but is already over the 64-character OpenAI
        cap is kept unchanged and warned about, without any rename log line.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        long_safe_name: str = "a" * 70
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[self._make_tool(long_safe_name)])

        # INFO level so that a rename line would be captured if one were logged.
        with self.assertLogs(self.ADAPTER_LOGGER, level=INFO) as captured:
            tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)
        output: str = "\n".join(captured.output)

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, long_safe_name)
        self.assertIn("is 70 characters long, over the 64-character OpenAI tool-name cap", output)
        self.assertNotIn("renamed to", output)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_skips_nameless_tools(self, mock_client_class: MagicMock) -> None:
        """
        A tool advertised with an empty or missing name is skipped with a warning
        that says so, rather than exposed under an empty name with a length
        warning, and the other tools are unaffected.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        empty_name: MagicMock = self._make_tool("")
        no_name: MagicMock = self._make_tool(None)
        good: MagicMock = self._make_tool("good_tool")
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[empty_name, no_name, good])

        with self.assertLogs(self.ADAPTER_LOGGER, level=WARNING) as captured:
            tools: List[StructuredTool] = await self.adapter.get_mcp_tools(self.SERVER_URL)
        output: str = "\n".join(captured.output)

        self.assertEqual(len(tools), 1)
        self.assertIs(tools[0], good)
        self.assertIn("advertised without a name", output)
        self.assertNotIn("characters long", output)

    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_ignores_non_string_allow_list_entries(self, mock_client_class: MagicMock) -> None:
        """
        Allow-list entries that are not non-empty strings are set aside with a
        warning instead of raising inside the name matching; the string entries
        still select their tools and are not reported as unmatched.

        :param mock_client_class: Patched MultiServerMCPClient class.
        """
        mock_client: MagicMock = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=self._make_tools(["good_tool", "other_tool"]))

        with self.assertLogs(self.ADAPTER_LOGGER, level=WARNING) as captured:
            tools: List[StructuredTool] = await self.adapter.get_mcp_tools(
                self.SERVER_URL, allowed_tools=[42, "", None, "good_tool"])
        output: str = "\n".join(captured.output)

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "good_tool")
        self.assertEqual(self.adapter.unmatched_allowed_tools, [])
        self.assertIn("are not non-empty strings", output)
        self.assertIn("42", output)
