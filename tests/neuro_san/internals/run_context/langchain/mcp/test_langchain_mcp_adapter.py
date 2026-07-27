
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

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch
import pytest

from langchain_core.tools import StructuredTool

from neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter import LangChainMcpAdapter


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
        tools = [
            MagicMock(spec=StructuredTool, name=f"tool{i}", tags=[])
            for i in range(3)
        ]

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=tools)

        result = await adapter.get_mcp_tools("https://mcp.example.com/mcp")

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
