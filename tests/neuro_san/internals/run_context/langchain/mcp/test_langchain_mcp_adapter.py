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

from httpx import Auth
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
        LangChainMcpAdapter._mcp_info = None
        yield
        LangChainMcpAdapter._mcp_info = None

    def test_init(self, adapter):
        """Test adapter initialization"""
        assert adapter.client_allowed_tools == []
        assert adapter.logger is not None

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_basic(self, mock_client_class, mock_servers_restorer_class,
                                       mock_oauth_factory_class, adapter, mock_mcp_tool):
        """Test basic retrieval of MCP tools"""
        # Setup restorer mocks
        mock_servers_restorer_class.return_value.restore.return_value = {}

        # Setup oauth mock to return None (no auth needed)
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=None)

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[mock_mcp_tool])

        server_url = "https://mcp.example.com/mcp"
        tools = await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data={})

        # Verify auth was not added to client config
        call_args = mock_client_class.call_args[0][0]
        assert "auth" not in call_args["server"]

        assert len(tools) == 1
        assert tools[0].name == "test_tool"
        assert "langchain_tool" in tools[0].tags
        mock_client_class.assert_called_once()
        mock_client.get_tools.assert_called_once()

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_allowed_tools_param(
        self, mock_client_class, mock_servers_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test filtering tools with allowed_tools parameter"""
        # Setup restorer mocks
        mock_servers_restorer_class.return_value.restore.return_value = {}

        # Setup oauth mock to return None (no auth needed)
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=None)

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
        tools = await adapter.get_mcp_tools(server_url, allowed_tools=allowed_tools, sly_data={})

        assert len(tools) == 1
        assert tools[0].name == "allowed_tool"
        assert adapter.client_allowed_tools == allowed_tools

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_config_allowed_tools(
        self, mock_client_class, mock_servers_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test filtering tools with allowed_tools from config"""
        server_url = "https://mcp.example.com/mcp"
        mock_servers_restorer_class.return_value.restore.return_value = {
            server_url: {
                "tools": ["config_tool"]
            }
        }

        # Setup oauth mock to return None (no auth needed)
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=None)

        tool1 = MagicMock(spec=StructuredTool)
        tool1.name = "config_tool"
        tool1.tags = []

        tool2 = MagicMock(spec=StructuredTool)
        tool2.name = "other_tool"
        tool2.tags = []

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[tool1, tool2])

        tools = await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data={})

        assert len(tools) == 1
        assert tools[0].name == "config_tool"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_headers_param(
        self, mock_client_class, mock_servers_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test MCP client initialization with headers parameter"""
        server_url = "https://mcp.example.com/mcp"
        sly_data = {
            "http_headers": {
                server_url: {"Authorization": "Bearer custom_token"}
            }
        }

        mock_servers_restorer_class.return_value.restore.return_value = {}

        # Setup oauth mock to return None (no auth needed)
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=None)

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data=sly_data)

        call_args = mock_client_class.call_args[0][0]
        assert "headers" in call_args["server"]
        assert call_args["server"]["headers"]["Authorization"] == "Bearer custom_token"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_config_headers(
        self, mock_client_class, mock_servers_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test MCP client initialization with headers from config"""
        server_url = "https://mcp.example.com/mcp"
        mock_servers_restorer_class.return_value.restore.return_value = {
            server_url: {
                "http_headers": {"Authorization": "Bearer config_token"}
            }
        }

        # Setup oauth mock to return None (no auth needed)
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=None)

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data={})

        call_args = mock_client_class.call_args[0][0]
        assert "headers" in call_args["server"]
        assert call_args["server"]["headers"]["Authorization"] == "Bearer config_token"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_invalid_headers_type(
        self, mock_client_class, mock_oauth_factory_class, adapter, caplog
    ):
        """Test handling of invalid headers type in config"""
        # pylint: disable=protected-access
        server_url = "https://mcp.example.com/mcp"
        LangChainMcpAdapter._mcp_info = {
            server_url: {
                "http_headers": "invalid_string_not_dict"
            }
        }

        # Setup oauth mock to return None (no auth needed)
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=None)

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data={})

        # Check that error was logged
        assert "must be a dictionary" in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_adds_langchain_tool_tags(
        self, mock_client_class, mock_servers_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test that langchain_tool tags are added to all tools"""
        mock_servers_restorer_class.return_value.restore.return_value = {}

        # Setup oauth mock to return None (no auth needed)
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=None)

        tools = [
            MagicMock(spec=StructuredTool, name=f"tool{i}", tags=[])
            for i in range(3)
        ]

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=tools)

        result = await adapter.get_mcp_tools("https://mcp.example.com/mcp", allowed_tools=None, sly_data={})

        for tool in result:
            assert "langchain_tool" in tool.tags

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_client_info_from_sly_data(
        self, mock_client_class, mock_info_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test that client info from sly_data is used for authentication"""
        server_url = "https://mcp.example.com/mcp"
        sly_data = {
            "mcp_client_info": {
                server_url: {
                    "client_id": "sly_data_client_id",
                    "client_secret": "sly_data_secret"
                }
            }
        }

        mock_info_restorer_class.return_value.restore.return_value = {}

        # Setup oauth mock
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=MagicMock(spec=Auth))

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data=sly_data)

        # Verify OauthProviderFactory was called with correct client_info
        mock_oauth_factory_class.assert_called_once()
        call_kwargs = mock_oauth_factory_class.call_args[1]
        assert call_kwargs["storage"].client_info["client_id"] == "sly_data_client_id"
        assert call_kwargs["storage"].client_info["client_secret"] == "sly_data_secret"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_client_info_from_config(
        self, mock_client_class, mock_info_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test that client info from config is used when not in sly_data"""
        server_url = "https://mcp.example.com/mcp"
        mock_info_restorer_class.return_value.restore.return_value = {
            server_url: {
                "mcp_client_info": {
                    "client_id": "config_client_id",
                    "client_secret": "config_secret"
                }
            }
        }

        # Setup oauth mock
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=MagicMock(spec=Auth))

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data={})

        # Verify OauthProviderFactory was called with config client_info
        mock_oauth_factory_class.assert_called_once()
        call_kwargs = mock_oauth_factory_class.call_args[1]
        assert call_kwargs["storage"].client_info["client_id"] == "config_client_id"
        assert call_kwargs["storage"].client_info["client_secret"] == "config_secret"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_sly_data_client_info_takes_priority(
        self, mock_client_class, mock_info_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test that sly_data client_info takes priority over config"""
        server_url = "https://mcp.example.com/mcp"
        sly_data = {
            "mcp_client_info": {
                server_url: {
                    "client_id": "sly_data_client_id",
                    "client_secret": "sly_data_secret"
                }
            }
        }

        mock_info_restorer_class.return_value.restore.return_value = {
            server_url: {
                "mcp_client_info": {
                    "client_id": "config_client_id",
                    "client_secret": "config_secret"
                }
            }
        }

        # Setup oauth mock
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=MagicMock(spec=Auth))

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data=sly_data)

        # Verify sly_data client_info was used, not config
        call_kwargs = mock_oauth_factory_class.call_args[1]
        assert call_kwargs["storage"].client_info["client_id"] == "sly_data_client_id"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_token_in_sly_data(
        self, mock_client_class, mock_info_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test that token from sly_data is used for authentication"""
        server_url = "https://mcp.example.com/mcp"
        sly_data = {
            "mcp_client_info": {
                server_url: {
                    "client_id": "test_client_id"
                }
            },
            "mcp_tokens": {
                server_url: {
                    "access_token": "existing_token",
                    "refresh_token": "existing_refresh"
                }
            }
        }

        mock_info_restorer_class.return_value.restore.return_value = {}

        # Setup oauth mock
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=MagicMock(spec=Auth))

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data=sly_data)

        # Verify token was passed to OauthProviderFactory
        call_kwargs = mock_oauth_factory_class.call_args[1]
        assert call_kwargs["storage"].tokens["access_token"] == "existing_token"
        assert call_kwargs["storage"].tokens["refresh_token"] == "existing_refresh"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_creates_mcp_tokens_dict_in_sly_data(
        self, mock_client_class, mock_info_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test that mcp_tokens dict is created in sly_data when client_info exists"""
        server_url = "https://mcp.example.com/mcp"
        sly_data = {
            "mcp_client_info": {
                server_url: {
                    "client_id": "test_client_id"
                }
            }
        }

        mock_info_restorer_class.return_value.restore.return_value = {}

        # Setup oauth mock
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=MagicMock(spec=Auth))

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data=sly_data)

        # Verify mcp_tokens dict was created in sly_data
        assert "mcp_tokens" in sly_data
        assert server_url in sly_data["mcp_tokens"]

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_invalid_client_info_type(
        self, mock_client_class, mock_info_restorer_class,
        mock_oauth_factory_class, adapter, caplog
    ):
        """Test handling of invalid client_info type"""
        server_url = "https://mcp.example.com/mcp"
        mock_info_restorer_class.return_value.restore.return_value = {
            server_url: {
                "mcp_client_info": "invalid_string_not_dict"
            }
        }

        # Setup oauth mock
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=None)

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data={})

        # Check that error was logged
        assert "MCP client info" in caplog.text
        assert "must be a dictionary" in caplog.text

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_invalid_token_type(
        self, mock_client_class, mock_info_restorer_class,
        mock_oauth_factory_class, adapter, caplog
    ):
        """Test handling of invalid token type in sly_data"""
        server_url = "https://mcp.example.com/mcp"
        sly_data = {
            "mcp_client_info": {
                server_url: {"client_id": "test_id"}
            },
            "mcp_tokens": {
                server_url: "invalid_string_not_dict"
            }
        }

        mock_info_restorer_class.return_value.restore.return_value = {}

        # Setup oauth mock
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=MagicMock(spec=Auth))

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data=sly_data)

        # Check that error was logged and token was reset to empty dict
        assert "Token for server" in caplog.text
        assert "must be a dictionary" in caplog.text
        assert not sly_data["mcp_tokens"][server_url]

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_token_endpoint_from_config(
        self, mock_client_class, mock_info_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test that token_endpoint from config is passed to OauthProviderFactory"""
        server_url = "https://mcp.example.com/mcp"
        mock_info_restorer_class.return_value.restore.return_value = {
            server_url: {
                "mcp_client_info": {"client_id": "test_id"},
                "mcp_server_info": {
                    "token_endpoint": "https://auth.example.com/token"
                }
            }
        }

        # Setup oauth mock
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=MagicMock(spec=Auth))

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data={})

        # Verify token_endpoint was passed to OauthProviderFactory
        call_kwargs = mock_oauth_factory_class.call_args[1]
        assert call_kwargs["token_endpoint"] == "https://auth.example.com/token"

    @pytest.mark.asyncio
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.OauthProviderFactory')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
    async def test_get_mcp_tools_with_auth_timeout_from_config(
        self, mock_client_class, mock_info_restorer_class,
        mock_oauth_factory_class, adapter
    ):
        """Test that auth_timeout from config is passed to OauthProviderFactory"""
        server_url = "https://mcp.example.com/mcp"
        mock_info_restorer_class.return_value.restore.return_value = {
            server_url: {
                "mcp_client_info": {"client_id": "test_id"},
                "auth_timeout": 600.0
            }
        }

        # Setup oauth mock
        mock_oauth_factory = mock_oauth_factory_class.return_value
        mock_oauth_factory.get_auth = AsyncMock(return_value=MagicMock(spec=Auth))

        mock_client = mock_client_class.return_value
        mock_client.get_tools = AsyncMock(return_value=[])

        await adapter.get_mcp_tools(server_url, allowed_tools=None, sly_data={})

        # Verify timeout was passed to OauthProviderFactory
        call_kwargs = mock_oauth_factory_class.call_args[1]
        assert call_kwargs["timeout"] == 600.0
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.McpServersInfoRestorer')
    @patch('neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter.MultiServerMCPClient')
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
        assert LangChainMcpAdapter._mcp_servers_info == {}
        # The real underlying cause is surfaced in the log so users can diagnose.
        assert "Cannot resolve variable ${YDC_API_KEY}" in caplog.text
