
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

import os
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import copy
from logging import Logger
from logging import getLogger
import threading

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.exceptions import OAuthTokenError


from neuro_san.internals.run_context.langchain.mcp.sly_data_token_storage import SlyDataTokenStorage
from neuro_san.internals.run_context.langchain.mcp.mcp_servers_info_restorer import McpServersInfoRestorer
from neuro_san.internals.run_context.langchain.mcp.oauth_provider_factory import OauthProviderFactory


class LangChainMcpAdapter:
    """
    Adapter class to fetch tools from a Multi-Client Protocol (MCP) server and return them as
    LangChain-compatible tools. This class provides static methods for interacting with MCP servers.

    Features:
    - Automatic OAuth authentication with multiple flow support
    - Tool filtering based on allowed lists
    - MCP server configuration management
    """

    _mcp_info_lock: threading.Lock = threading.Lock()
    _mcp_servers_info: Dict[str, Any] = None

    def __init__(self):
        """
        Constructor
        """
        self.client_allowed_tools: List[str] = []
        self.logger: Logger = getLogger(self.__class__.__name__)

    @staticmethod
    def _load_mcp_servers_info():
        """
        Loads MCP servers information from a configuration file if not already loaded.
        """
        with LangChainMcpAdapter._mcp_info_lock:
            if LangChainMcpAdapter._mcp_servers_info is None:
                LangChainMcpAdapter._mcp_servers_info = McpServersInfoRestorer().restore()
                if LangChainMcpAdapter._mcp_servers_info is None:
                    # Something went wrong reading the file.
                    # Prevent further attempts to load info.
                    LangChainMcpAdapter._mcp_servers_info = {}

    def _get_server_info(self, server_url: str) -> Dict[str, Any]:
        """
        Get server configuration from cached info.

        :param server_url: The MCP server URL to look up configuration for.

        :return: Server configuration dictionary (empty dict if not found).
        """
        if self._mcp_servers_info is None:
            self._load_mcp_servers_info()
        return self._mcp_servers_info.get(server_url, {})

    def _prepare_headers(
        self,
        server_url: str,
        headers: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Prepare headers for MCP request.

        Priority: explicitly provided headers > server config headers

        :param server_url: The MCP server URL to get configuration for.
        :param headers: Explicitly provided headers (optional).

        :return: Headers dictionary or None if no headers are available or invalid.
        """
        # Use provided headers, fallback to server config
        server_info = self._get_server_info(server_url)
        final_headers = headers or server_info.get("http_headers")

        if final_headers:
            if not isinstance(final_headers, dict):
                self.logger.error(
                    "MCP client headers for server %s must be a dictionary, got %s",
                    server_url,
                    type(final_headers).__name__
                )
                return None
            # Return a copy to avoid modifying the original
            return copy.copy(final_headers)

        return None

    def _create_oauth_provider(
            self, server_url: str, client_info: Dict[str, Any], token: Dict[str, Any]) -> OauthProviderFactory:
        """
        Create and configure OAuth provider for the server.

        :param server_url: The MCP server URL to create OAuth provider for.

        :return: Configured OAuth provider factory instance.
        """
        server_info = self._get_server_info(server_url)

        # Prepare token storage
        storage = SlyDataTokenStorage(client_info, token)

        # Get OAuth endpoints from server config (optional - will be discovered if not provided)
        auth_endpoint = server_info.get("authorization_endpoint")
        token_endpoint = server_info.get("token_endpoint")

        # Get callback port from environment or use default
        callback_port_env = os.environ.get("AGENT_MCP_CALLBACK_PORT")
        callback_port = int(callback_port_env) if callback_port_env else 3000

        return OauthProviderFactory(
            server_url=server_url,
            storage=storage,
            auth_endpoint=auth_endpoint,
            token_endpoint=token_endpoint,
            callback_port=callback_port
        )

    def _determine_allowed_tools(
        self,
        server_url: str,
        allowed_tools: Optional[List[str]]
    ) -> List[str]:
        """
        Determine which tools are allowed.

        Priority: explicitly provided allowed_tools > server config tools > all tools

        :param server_url: The MCP server URL to get tool configuration for.
        :param allowed_tools: Explicitly provided allowed tools list (optional).

        :return: List of allowed tool names (empty list means all tools allowed).
        """
        if allowed_tools is not None:
            return allowed_tools

        # Fallback to server config
        server_info = self._get_server_info(server_url)
        return server_info.get("tools", [])

    def _filter_and_tag_tools(
        self,
        tools: List[BaseTool],
        allowed_tools: List[str]
    ) -> List[BaseTool]:
        """
        Filter tools based on allowed list and add langchain_tool tags.

        :param tools: List of all tools from MCP server.
        :param allowed_tools: List of allowed tool names (empty list = allow all).

        :return: Filtered list of tools with tags added.
        """
        # Filter if allowed_tools is not empty
        if allowed_tools:
            tools = [tool for tool in tools if tool.name in allowed_tools]

        # Add tags to all tools
        for tool in tools:
            # Add "langchain_tool" tag so journal callback can identify it
            # These MCP tools are treated as LangChain tools and can be reported in the thinking file
            tool.tags = ["langchain_tool"]

        return tools

    async def get_mcp_tools(
        self,
        server_url: str,
        allowed_tools: Optional[List[str]] = None,
        headers: Optional[Dict[str, Any]] = None,
        client_info: Optional[Dict[str, Any]] = None,
        token: Optional[Dict[str, Any]] = None
    ) -> List[BaseTool]:
        """
        Fetches tools from the given MCP server and returns them as LangChain-compatible tools.

        The method handles:
        - OAuth authentication (client_credentials, authorization_code, or dynamic registration)
        - Tool filtering based on allowed list
        - Automatic session management and cleanup

        :param server_url: URL of the MCP server, e.g. https://mcp.deepwiki.com/mcp or http://localhost:8000/mcp/
        :param allowed_tools: Optional list of tool names to filter from the server's available tools.
                              If None, uses server config tools or all tools from the server will be returned.
        :param headers: Optional dictionary of HTTP headers to include in the MCP requests.
                        If None, uses headers from server configuration.

        :return: A list of LangChain BaseTool instances retrieved from the MCP server.
        """
        # Prepare MCP tool configuration
        mcp_tool_dict: Dict[str, Any] = {
            "url": server_url,
            "transport": "streamable_http",
        }

        # Add headers if available
        prepared_headers = self._prepare_headers(server_url, headers)
        if prepared_headers:
            mcp_tool_dict["headers"] = prepared_headers

        # Create and configure OAuth provider
        provider = self._create_oauth_provider(server_url, client_info, token)

        try:
            # Get OAuth authentication
            auth = await provider.get_auth()
            mcp_tool_dict["auth"] = auth

            # Create MCP client
            client = MultiServerMCPClient({"server": mcp_tool_dict})

            # Fetch tools from server
            # The get_tools() method uses `async with create_session(...)` internally,
            # which guarantees proper session cleanup even if errors occur.
            # See: https://github.com/langchain-ai/langchain-mcp-adapters/blob/main/langchain_mcp_adapters/tools.py#L164
            mcp_tools: List[BaseTool] = await client.get_tools()

        except (OAuthFlowError, OAuthTokenError):
            # Clean up OAuth resources before re-raising
            await provider.cleanup()
            raise
        finally:
            # Always clean up OAuth resources (callback server and empty storage)
            await provider.cleanup()

        # Determine which tools are allowed
        client_allowed_tools = self._determine_allowed_tools(server_url, allowed_tools)

        # Store for instance reference
        self.client_allowed_tools = client_allowed_tools

        # Filter and tag tools
        mcp_tools = self._filter_and_tag_tools(mcp_tools, client_allowed_tools)

        return mcp_tools
