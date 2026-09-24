
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

from typing import List

from logging import INFO

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch
import pytest

from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp.types import CallToolResult
from mcp.types import TextContent
from mcp.types import Tool as McpTool

from neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter import LangChainMcpAdapter


# One test class per source class is the repo convention, so the test count grows with the class.
# pylint: disable=too-many-public-methods
class TestLangChainMcpAdapter:
    """Test suite for LangChainMcpAdapter class"""

    @pytest.fixture
    def adapter(self):
        """Create a fresh adapter instance for each test"""
        return LangChainMcpAdapter()

    @pytest.fixture
    def mock_mcp_tool(self):
        """Create a mock MCP tool"""
        tool = MagicMock(spec=StructuredTool)
        tool.name = "test_tool"
        tool.tags = []
        return tool

    @pytest.fixture(autouse=True)
    def reset_class_state(self):
        """Reset class-level state before and after each test"""
        # pylint: disable=protected-access
        LangChainMcpAdapter._mcp_servers_info = None
        yield
        LangChainMcpAdapter._mcp_servers_info = None

    @staticmethod
    def _make_tool(name: str) -> MagicMock:
        """
        Builds a StructuredTool-shaped mock carrying a real string name.

        The name must be assigned after construction: MagicMock's name= kwarg
        only sets the mock's repr, and with spec=StructuredTool reading .name
        without an explicit assignment raises AttributeError.

        :param name: The tool name the fake MCP server advertises.
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

    def test_init(self, adapter):
        """Test adapter initialization"""
        assert adapter.client_allowed_tools == []
        assert adapter.logger is not None

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_basic(self, mock_client_class, adapter, mock_mcp_tool):
        """Test basic retrieval of MCP tools"""
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[mock_mcp_tool])

        server_url = "https://mcp.example.com/mcp"
        tools = await adapter.get_mcp_tools(server_url)

        assert len(tools) == 1
        assert tools[0].name == "test_tool"
        assert "langchain_tool" in tools[0].tags
        mock_client_class.assert_called_once()
        mock_client.get_tools.assert_called_once()

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_allowed_tools_param(
        self, mock_client_class, adapter
    ):
        """Test filtering tools with allowed_tools parameter"""
        tool1 = MagicMock(spec=StructuredTool)
        tool1.name = "allowed_tool"
        tool1.tags = []

        tool2 = MagicMock(spec=StructuredTool)
        tool2.name = "disallowed_tool"
        tool2.tags = []

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[tool1, tool2])

        server_url = "https://mcp.example.com/mcp"
        allowed_tools = ["allowed_tool"]
        tools = await adapter.get_mcp_tools(server_url, allowed_tools=allowed_tools)

        assert len(tools) == 1
        assert tools[0].name == "allowed_tool"
        assert adapter.client_allowed_tools == allowed_tools

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpServersInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_config_allowed_tools(
        self, mock_client_class, mock_restorer_class, adapter
    ):
        """Test filtering tools with allowed_tools from config"""
        server_url = "https://mcp.example.com/mcp"
        mock_restorer = mock_restorer_class.return_value
        mock_restorer.restore.return_value = {
            server_url: {
                "tools": ["config_tool"]
            }
        }

        tool1 = MagicMock(spec=StructuredTool)
        tool1.name = "config_tool"
        tool1.tags = []

        tool2 = MagicMock(spec=StructuredTool)
        tool2.name = "other_tool"
        tool2.tags = []

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[tool1, tool2])

        tools = await adapter.get_mcp_tools(server_url)

        assert len(tools) == 1
        assert tools[0].name == "config_tool"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpServersInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_headers_param(
        self, mock_client_class, mock_restorer_class, adapter
    ):
        """Test MCP client initialization with headers parameter"""
        server_url = "https://mcp.example.com/mcp"
        headers = {"Authorization": "Bearer custom_token"}

        mock_restorer = mock_restorer_class.return_value
        mock_restorer.restore.return_value = {}

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, headers=headers)

        call_args = mock_client_class.call_args[0][0]
        assert "headers" in call_args["server"]
        assert call_args["server"]["headers"]["Authorization"] == "Bearer custom_token"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpServersInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_config_headers(
        self, mock_client_class, mock_restorer_class, adapter
    ):
        """Test MCP client initialization with headers from config"""
        server_url = "https://mcp.example.com/mcp"
        mock_restorer = mock_restorer_class.return_value
        mock_restorer.restore.return_value = {
            server_url: {
                "http_headers": {"Authorization": "Bearer config_token"}
            }
        }

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url)

        call_args = mock_client_class.call_args[0][0]
        assert "headers" in call_args["server"]
        assert call_args["server"]["headers"]["Authorization"] == "Bearer config_token"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_invalid_headers_type(
        self, mock_client_class, adapter, caplog
    ):
        """Test handling of invalid headers type in config"""
        # pylint: disable=protected-access
        server_url = "https://mcp.example.com/mcp"
        LangChainMcpAdapter._mcp_servers_info = {
            server_url: {
                "http_headers": "invalid_string_not_dict"
            }
        }

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url)

        # Check that error was logged
        assert "must be a dictionary" in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_adds_langchain_tool_tags(
        self, mock_client_class, adapter
    ):
        """Test that langchain_tool tags are added to all tools"""
        # Names are assigned explicitly: MagicMock(name=...) only sets the repr,
        # and the adapter now reads tool.name on every tool to check it is safe.
        tools: List[MagicMock] = []
        for index in range(3):
            tools.append(self._make_tool(f"tool{index}"))

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=tools)

        result = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

        assert len(result) == 3
        for tool in result:
            assert "langchain_tool" in tool.tags

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_wraps_tool_errors(self, mock_client_class, adapter, caplog):
        """A tool whose MCP call raises (e.g. an HTTP 504 from a gateway timeout)
        must return a concise "Error: ..." tool output instead of propagating the
        exception and aborting the whole agent chain. The full traceback stays in
        the server log. See https://github.com/cognizant-ai-lab/neuro-san/issues/1097"""

        tool = StructuredTool(
            name="wolfram",
            description="test tool",
            args_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            coroutine=AsyncMock(
                side_effect=RuntimeError("Server error '504 Gateway Time-out' for url 'https://mcp.example.com/mcp'")
            ),
            response_format="content_and_artifact",
        )

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[tool])

        tools = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

        # Invoking the tool does not raise; the LLM sees a concise error message.
        result = await tools[0].ainvoke({"query": "toss a coin 10 million times"})
        assert result == \
            "Error: RuntimeError: Server error '504 Gateway Time-out' for url 'https://mcp.example.com/mcp'"
        # The full traceback is preserved in the server log for debugging.
        assert "RuntimeError" in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_unwraps_exception_groups(self, mock_client_class, adapter):
        """When the MCP transport fails at call time, anyio raises an ExceptionGroup
        whose str() is just "unhandled errors in a TaskGroup (1 sub-exception)".
        The tool output must surface the underlying cause instead of that summary."""

        tool = StructuredTool(
            name="wolfram",
            description="test tool",
            args_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            coroutine=AsyncMock(
                side_effect=ExceptionGroup(
                    "unhandled errors in a TaskGroup",
                    [ConnectionError("All connection attempts failed")],
                )
            ),
            response_format="content_and_artifact",
        )

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[tool])

        tools = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

        result = await tools[0].ainvoke({"query": "toss a coin 10 million times"})
        # The real cause is in the output, not just the TaskGroup summary.
        assert "ConnectionError: All connection attempts failed" in result

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_wrapped_tools_pass_through_results(self, mock_client_class, adapter):
        """The error wrapping must not disturb normal (non-raising) tool results."""

        tool = StructuredTool(
            name="wolfram",
            description="test tool",
            args_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            coroutine=AsyncMock(return_value=("42", None)),
            response_format="content_and_artifact",
        )

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[tool])

        tools = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

        result = await tools[0].ainvoke({"query": "6 times 7"})
        assert result == "42"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpServersInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    # pylint: disable=too-many-arguments, too-many-positional-arguments
    async def test_get_mcp_tools_proceeds_when_restore_raises_value_error(
        self, mock_client_class, mock_restorer_class, adapter, mock_mcp_tool, caplog
    ):
        """A malformed mcp_info config (restore() raising ValueError) must not hang or
        propagate; get_mcp_tools should log a warning and proceed with an empty servers
        info dict."""
        # pylint: disable=protected-access
        mock_restorer = mock_restorer_class.return_value
        mock_restorer.restore.side_effect = ValueError(
            'There was an error loading MCP servers info file "mcp_info.hocon".\n'
            "Underlying error (ConfigSubstitutionException): "
            "Cannot resolve variable ${YDC_API_KEY} (line: 68, col: 39)"
        )

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[mock_mcp_tool])

        tools = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

        # The tool fetch still completes — the load failure does not propagate.
        assert len(tools) == 1
        # Fallback to the empty dict so subsequent lookups don't blow up.
        # pylint: disable=use-implicit-booleaness-not-comparison
        assert LangChainMcpAdapter._mcp_servers_info == {}
        # The real underlying cause is surfaced in the log so users can diagnose.
        assert "Cannot resolve variable ${YDC_API_KEY}" in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_renames_only_unsafe_names(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        A server tool named with a "/" is exposed to the LLM under the
        provider-safe "__" spelling and the rename is logged at INFO, while a
        tool whose name is already safe is returned unchanged with no log line.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        # The routine rename is INFO, below caplog's default WARNING threshold.
        caplog.set_level(INFO)
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=self._make_tools(["basic/music_nerd_pro", "Safe_tool-1"]))

        tools: List[StructuredTool] = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

        assert len(tools) == 2
        assert tools[0].name == "basic__music_nerd_pro"
        assert tools[1].name == "Safe_tool-1"
        assert "langchain_tool" in tools[0].tags
        assert "tool 'basic/music_nerd_pro' renamed to 'basic__music_nerd_pro'" in caplog.text
        # The operator must be told the server still sees the original name.
        assert "still called with the original name" in caplog.text
        assert "'Safe_tool-1' renamed" not in caplog.text
        assert "match no tool" not in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_allow_list_accepts_either_spelling(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        An allow-list entry keeps the matching "/" server tool whether written in
        the server's original spelling or in the provider-safe spelling seen in
        logs and thinking output. An entry matching nothing yields no tools and
        logs a warning naming the entry and the tools the server does offer,
        instead of dropping it silently.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        server_names: List[str] = ["basic/music_nerd_pro", "other_tool"]
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(side_effect=[
            self._make_tools(server_names),
            self._make_tools(server_names),
            self._make_tools(server_names),
        ])
        server_url: str = "https://mcp.example.com/mcp"

        original_spelling: List[StructuredTool] = await adapter.get_mcp_tools(
            server_url, allowed_tools=["basic/music_nerd_pro"])
        safe_spelling: List[StructuredTool] = await adapter.get_mcp_tools(
            server_url, allowed_tools=["basic__music_nerd_pro"])
        assert "match no tool" not in caplog.text
        unmatched: List[StructuredTool] = await adapter.get_mcp_tools(server_url, allowed_tools=["nope"])

        assert len(original_spelling) == 1
        assert original_spelling[0].name == "basic__music_nerd_pro"
        assert len(safe_spelling) == 1
        assert safe_spelling[0].name == "basic__music_nerd_pro"
        assert len(unmatched) == 0
        assert "match no tool on the server" in caplog.text
        assert "nope" in caplog.text
        assert "basic/music_nerd_pro" in caplog.text
        assert "other_tool" in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_allow_list_exact_spelling_selects_one_tool(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        When a server offers both "a/b" and "a__b", an allow list naming "a/b"
        keeps exactly the "a/b" tool (then renamed) and one naming "a__b" keeps
        exactly the literal "a__b" tool. Neither case is a collision, so nothing
        is skipped and the author never silently gets the tool they did not name.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        first_slash: MagicMock = self._make_tool("a/b")
        first_safe: MagicMock = self._make_tool("a__b")
        second_slash: MagicMock = self._make_tool("a/b")
        second_safe: MagicMock = self._make_tool("a__b")
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(side_effect=[[first_slash, first_safe], [second_slash, second_safe]])
        server_url: str = "https://mcp.example.com/mcp"

        by_slash: List[StructuredTool] = await adapter.get_mcp_tools(server_url, allowed_tools=["a/b"])
        by_safe: List[StructuredTool] = await adapter.get_mcp_tools(server_url, allowed_tools=["a__b"])

        assert len(by_slash) == 1
        # Identity, not just name: the "a/b" tool the author asked for is the survivor.
        assert by_slash[0] is first_slash
        assert by_slash[0].name == "a__b"
        assert len(by_safe) == 1
        assert by_safe[0] is second_safe
        assert by_safe[0].name == "a__b"
        assert "skipping it" not in caplog.text
        assert "match no tool" not in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_skips_colliding_tools(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Without an allow list, two tools mapping to one safe name are a collision:
        the tool needing no rename wins even when listed second ("a/b" vs "a__b"),
        and when both need renaming the first one listed wins ("a.b" vs "a b").
        The loser is skipped with a warning either way.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        slash_tool: MagicMock = self._make_tool("a/b")
        safe_tool: MagicMock = self._make_tool("a__b")
        dot_tool: MagicMock = self._make_tool("a.b")
        space_tool: MagicMock = self._make_tool("a b")
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(side_effect=[[slash_tool, safe_tool], [dot_tool, space_tool]])
        server_url: str = "https://mcp.example.com/mcp"

        safe_wins: List[StructuredTool] = await adapter.get_mcp_tools(server_url)
        first_wins: List[StructuredTool] = await adapter.get_mcp_tools(server_url)

        assert len(safe_wins) == 1
        # Identity, not just name: the literal "a__b" tool is the survivor.
        assert safe_wins[0] is safe_tool
        assert safe_wins[0].name == "a__b"
        assert "tool 'a/b' would be renamed to 'a__b'" in caplog.text
        assert "skipping it" in caplog.text
        assert len(first_wins) == 1
        assert first_wins[0] is dot_tool
        assert first_wins[0].name == "a_b"
        assert "tool 'a b' would be renamed to 'a_b'" in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_warns_when_renamed_name_exceeds_soft_limit(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        A rename that pushes a name past the 64-character OpenAI cap is kept
        (Anthropic and local providers accept it) but a warning is logged.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        # 34 + "/" + 34 = 69 chars originally; "__" makes the safe name 70 chars.
        original_name: str = ("a" * 34) + "/" + ("b" * 34)
        expected_name: str = ("a" * 34) + "__" + ("b" * 34)
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[self._make_tool(original_name)])

        tools: List[StructuredTool] = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

        assert len(tools) == 1
        assert len(expected_name) == 70
        assert tools[0].name == expected_name
        assert "over the 64-character OpenAI tool-name cap" in caplog.text
        assert "is 70 characters long" in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_renames_real_tool_and_still_calls_server_with_original_name(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter
    ) -> None:
        """
        On a real StructuredTool built by langchain_mcp_adapters, the rename is
        accepted by the model, the renamed tool can be invoked, and the MCP
        session is still asked for the original name, because the coroutine
        closed over the original mcp.types.Tool.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        """
        session: MagicMock = MagicMock()
        session.call_tool = AsyncMock(return_value=CallToolResult(content=[TextContent(type="text", text="pong")]))
        mcp_tool: McpTool = McpTool(
            name="deep/echo_guy",
            description="echoes",
            inputSchema={"type": "object", "properties": {"user_message": {"type": "string"}},
                         "required": ["user_message"]})
        real_tool: StructuredTool = convert_mcp_tool_to_langchain_tool(session, mcp_tool)
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[real_tool])

        tools: List[StructuredTool] = await adapter.get_mcp_tools("https://mcp.example.com/mcp")
        result: str = await tools[0].ainvoke({"user_message": "ping"})

        assert tools[0] is real_tool
        assert real_tool.name == "deep__echo_guy"
        assert result == "pong"
        # The first positional argument of ClientSession.call_tool() is the tool name.
        assert session.call_tool.await_args.args[0] == "deep/echo_guy"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_records_unmatched_allow_list_entries(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        unmatched_allowed_tools holds exactly the allow-list entries that matched
        no advertised tool in either spelling, so BaseToolFactory can report them
        instead of comparing the entries with the renamed tools. It is reset on
        every call and empty without an allow list.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        server_names: List[str] = ["basic/music_nerd_pro", "other_tool"]
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(side_effect=[
            self._make_tools(server_names),
            self._make_tools(server_names),
            self._make_tools(server_names),
        ])
        server_url: str = "https://mcp.example.com/mcp"

        await adapter.get_mcp_tools(server_url, allowed_tools=["basic/music_nerd_pro", "nope"])
        assert adapter.unmatched_allowed_tools == ["nope"]
        assert "nope" in caplog.text

        await adapter.get_mcp_tools(server_url, allowed_tools=["basic__music_nerd_pro", "other_tool"])
        assert adapter.unmatched_allowed_tools == []

        await adapter.get_mcp_tools(server_url)
        assert adapter.unmatched_allowed_tools == []

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_allow_listed_pair_that_collides_keeps_the_first(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Naming both "a.b" and "a b" in the allow list does not exempt them from
        collision handling: both rename to "a_b", the first one listed is kept
        and the second is skipped with a warning.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        dot_tool: MagicMock = self._make_tool("a.b")
        space_tool: MagicMock = self._make_tool("a b")
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[dot_tool, space_tool])

        tools: List[StructuredTool] = await adapter.get_mcp_tools(
            "https://mcp.example.com/mcp", allowed_tools=["a.b", "a b"])

        assert len(tools) == 1
        assert tools[0] is dot_tool
        assert tools[0].name == "a_b"
        assert "tool 'a b' would be renamed to 'a_b'" in caplog.text
        assert adapter.unmatched_allowed_tools == []

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpServersInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_config_allow_list_accepts_safe_spelling(
        self, mock_client_class: MagicMock, mock_restorer_class: MagicMock, adapter: LangChainMcpAdapter
    ) -> None:
        """
        An allow list taken from the MCP servers info file goes through the same
        either-spelling matching as one passed in: a provider-safe entry selects
        the "/" tool the server advertises, which is then renamed.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param mock_restorer_class: Patched McpServersInfoRestorer class.
        :param adapter: Fresh adapter under test.
        """
        server_url: str = "https://mcp.example.com/mcp"
        mock_restorer = mock_restorer_class.return_value
        mock_restorer.restore.return_value = {server_url: {"tools": ["basic__music_nerd_pro"]}}
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=self._make_tools(["basic/music_nerd_pro", "other_tool"]))

        tools: List[StructuredTool] = await adapter.get_mcp_tools(server_url)

        assert len(tools) == 1
        assert tools[0].name == "basic__music_nerd_pro"
        assert adapter.unmatched_allowed_tools == []

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_allow_list_against_empty_server_warns(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        A server that advertises nothing leaves every allow-list entry unmatched:
        no tools come back, and the warning shows the empty server list.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        tools: List[StructuredTool] = await adapter.get_mcp_tools(
            "https://mcp.example.com/mcp", allowed_tools=["some_tool"])

        assert tools == []
        assert adapter.unmatched_allowed_tools == ["some_tool"]
        assert "Available tools: []" in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_warns_when_renamed_name_exceeds_hard_limit(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        A rename that pushes a name past the 128-character cap is still kept, but
        the warning names that cap rather than only OpenAI's 64.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        original_name: str = ("a" * 100) + "/" + ("b" * 100)
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[self._make_tool(original_name)])

        tools: List[StructuredTool] = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

        assert len(tools) == 1
        assert len(tools[0].name) == 202
        assert "over the 128-character tool-name cap" in caplog.text
        assert "is 202 characters long" in caplog.text
        assert "over the 64-character OpenAI tool-name cap" not in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_skips_duplicate_safe_names(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        A server that advertises one already-safe name twice yields that tool once:
        the first is kept, the duplicate is skipped with a warning, and unrelated
        tools are unaffected.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        first: MagicMock = self._make_tool("search")
        duplicate: MagicMock = self._make_tool("search")
        other: MagicMock = self._make_tool("other_tool")
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[first, duplicate, other])

        tools: List[StructuredTool] = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

        assert len(tools) == 2
        assert tools[0] is first
        assert tools[1] is other
        assert "tool 'search' is advertised more than once" in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_warns_when_unchanged_name_exceeds_soft_limit(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        A name that needs no rename but is already over the 64-character OpenAI
        cap is kept unchanged and warned about, without any rename log line.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        caplog.set_level(INFO)
        long_safe_name: str = "a" * 70
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[self._make_tool(long_safe_name)])

        tools: List[StructuredTool] = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

        assert len(tools) == 1
        assert tools[0].name == long_safe_name
        assert "is 70 characters long, over the 64-character OpenAI tool-name cap" in caplog.text
        assert "renamed to" not in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_skips_nameless_tools(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        A tool advertised with an empty or missing name is skipped with a warning
        that says so, rather than exposed under an empty name with a length
        warning, and the other tools are unaffected.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        empty_name: MagicMock = self._make_tool("")
        no_name: MagicMock = self._make_tool(None)
        good: MagicMock = self._make_tool("good_tool")
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[empty_name, no_name, good])

        tools: List[StructuredTool] = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

        assert len(tools) == 1
        assert tools[0] is good
        assert "advertised without a name" in caplog.text
        assert "characters long" not in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_ignores_non_string_allow_list_entries(
        self, mock_client_class: MagicMock, adapter: LangChainMcpAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Allow-list entries that are not non-empty strings are set aside with a
        warning instead of raising inside the name matching; the string entries
        still select their tools and are not reported as unmatched.

        :param mock_client_class: Patched MultiServerMCPClient class.
        :param adapter: Fresh adapter under test.
        :param caplog: pytest log capture fixture.
        """
        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=self._make_tools(["good_tool", "other_tool"]))

        tools: List[StructuredTool] = await adapter.get_mcp_tools(
            "https://mcp.example.com/mcp", allowed_tools=[42, "", None, "good_tool"])

        assert len(tools) == 1
        assert tools[0].name == "good_tool"
        assert adapter.unmatched_allowed_tools == []
        assert "are not non-empty strings" in caplog.text
        assert "42" in caplog.text
