
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
import threading
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import copy
from logging import Logger
from logging import getLogger
from httpx import Auth

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.exceptions import OAuthTokenError


from neuro_san.internals.run_context.langchain.mcp.mcp_info_restorer import McpInfoRestorer
from neuro_san.internals.run_context.langchain.mcp.oauth_provider_factory import OauthProviderFactory
from neuro_san.internals.run_context.langchain.mcp.sly_data_token_storage import SlyDataTokenStorage

MCP_AUTH_TIMEOUT = float(os.getenv("AGENT_MCP_TIMEOUT_SECONDS", "300.0"))  # Default to 5 minutes if not set


class LangChainMcpAdapter:
    """
    Adapter class to fetch tools from a Multi-Client Protocol (MCP) server and return them as
    LangChain-compatible tools. This class provides static methods for interacting with MCP servers.

    Features:
    - Automatic OAuth authentication with multiple flow support
    - Tool filtering based on allowed lists
    - MCP client and server configuration management
    """

    _mcp_info_lock: threading.Lock = threading.Lock()
    _mcp_info: Dict[str, Any] = None

    def __init__(self):
        """
        Constructor
        """
        self.client_allowed_tools: List[str] = []
        self.logger: Logger = getLogger(self.__class__.__name__)

    def _load_mcp_info(self):
        """
        Loads MCP clients and servers information from a configuration file if not already loaded.
        """
        # Write through the class so the cache stays shared across instances.
        # `self._mcp_info = ...` would create an instance attribute that shadows
        # the class attribute, leaving the class-level cache stuck at None and causing
        # every new LangChainMcpAdapter to reload (and re-log) the config.
        with LangChainMcpAdapter._mcp_info_lock:
            if LangChainMcpAdapter._mcp_info is None:
                try:
                    LangChainMcpAdapter._mcp_info = McpInfoRestorer().restore()
                except ValueError as value_error:
                    self.logger.warning("Error occurred while loading MCP info: %s", value_error)
                    self.logger.info("Proceeding with empty MCP info.")
                if LangChainMcpAdapter._mcp_info is None:
                    # Something went wrong reading the file.
                    # Prevent further attempts to load info.
                    LangChainMcpAdapter._mcp_info = {}

    async def _get_mcp_info(self, server_url: str) -> Dict[str, Any]:
        """
        Get client and server configuration from cached info.

        :param server_url: The MCP server URL to look up configuration for.

        :return: Server configuration dictionary (empty dict if not found).
        """
        if self._mcp_info is None:
            self._load_mcp_info()
        return self._mcp_info.get(server_url, {})

    async def _prepare_headers(
        self,
        server_url: str,
        headers: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Prepare headers for MCP request.

        Priority: explicitly provided headers > server config headers

        :param server_url: The MCP server URL to get configuration for.
        :param headers: Explicitly provided headers from sly data (optional).

        :return: Headers dictionary or None if no headers are available or invalid.
        """
        # Use provided headers, fallback to server config
        mcp_info: Dict[str, Any] = await self._get_mcp_info(server_url)
        final_headers: Dict[str, Any] = headers or mcp_info.get("http_headers")

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

    async def _prepare_client_info(self, server_url: str, client_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Prepare client info for MCP authentication.

        Priority: client info from sly data > client info from environment variable

        :param server_url: The MCP server URL to get configuration for.
        :param client_info: Client info from sly data (optional).

        :return: Client info dictionary or an empty dict if no client info are available or invalid.
        """
        # Use sly data client info, fallback to environment variable
        mcp_info: Dict[str, Any] = await self._get_mcp_info(server_url)
        final_client_info: Dict[str, Any] = client_info or mcp_info.get("mcp_client_info")

        if final_client_info:
            if not isinstance(final_client_info, dict):
                self.logger.error(
                    "MCP client info for server %s must be a dictionary, got %s",
                    server_url,
                    type(final_client_info).__name__
                )
                return {}
            # Return a copy to avoid modifying the original
            return copy.copy(final_client_info)

        return {}

    async def _prepare_token(
            self,
            server_url: str,
            sly_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Prepare token for MCP authentication. sly_data is needed as a reference to store the generated token.
        Only allow tokens that are explicitly configured in sly_data.

        :param server_url: The MCP server URL to get configuration for.
        :param sly_data: The sly data dictionary to use for token lookup and storage.

        :return: Token dictionary or an empty dict if no token are available or invalid.
        """
        # Ensure tokens dict exists in sly_data
        sly_data_tokens: Dict[str, Any] = sly_data.setdefault("mcp_tokens", {})

        # Get token from sly_data or env var
        sly_data_token: Dict[str, Any] = sly_data_tokens.get(server_url)

        if sly_data_token:
            if not isinstance(sly_data_token, dict):
                self.logger.error(
                    "Token for server %s must be a dictionary, got %s",
                    server_url,
                    type(sly_data_token).__name__
                )
                sly_data_tokens[server_url] = {}

        # Ensure server has an entry (either existing or empty dict)
        return sly_data_tokens.setdefault(server_url, {})

    async def _create_oauth_provider(
            self, server_url: str, client_info: Dict[str, Any], token: Dict[str, Any]) -> OauthProviderFactory:
        """
        Create and configure OAuth provider for the server.

        :param server_url: The MCP server URL to create OAuth provider for.

        :return: Configured OAuth provider factory instance.
        """
        mcp_info: Dict[str, Any] = await self._get_mcp_info(server_url)
        server_info: Dict[str, Any] = mcp_info.get("mcp_server_info", {})

        # Prepare token storage
        storage = SlyDataTokenStorage(client_info, token)

        # Get OAuth endpoints from server config (optional - will be discovered if not provided)
        token_endpoint: str = server_info.get("token_endpoint")

        # Get timeout for OAuth flows from server config or use default
        timeout: float = mcp_info.get("auth_timeout", MCP_AUTH_TIMEOUT)

        return OauthProviderFactory(
            server_url=server_url,
            storage=storage,
            token_endpoint=token_endpoint,
            timeout=timeout
        )

    async def _determine_allowed_tools(
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
        server_info = await self._get_mcp_info(server_url)
        return server_info.get("tools", [])

    async def _filter_and_tag_tools(
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
            filtered_tools: List[BaseTool] = []
            for tool in tools:
                if tool.name in allowed_tools:
                    filtered_tools.append(tool)
            tools = filtered_tools

        # Add tags to all tools
        for tool in tools:
            # Add "langchain_tool" tag so journal callback can identify it
            # These MCP tools are treated as LangChain tools and can be reported in the thinking file
            tool.tags = ["langchain_tool"]

        return tools

    async def _prepare_auth(self, server_url: str, sly_data: Dict[str, Any]) -> Optional[Auth]:
        """
        Prepare auth provider for MCP server if authentication is needed.

        :param server_url: URL of the MCP server, e.g. https://mcp.deepwiki.com/mcp or http://localhost:8000/mcp/
        :param sly_data: Optional dictionary of sly data (client info, token, headers) to use for MCP requests.

        :return: An Auth object for MCP authentication if needed, otherwise None.
        """
        # Get client info from env var if not available in sly data
        sly_data_client_info: Dict[str, Any] = sly_data.get("mcp_client_info", {}).get(server_url)
        client_info: Dict[str, Any] = await self._prepare_client_info(server_url, sly_data_client_info)
        token: Dict[str, Any] = {}
        if client_info:
            # If there is client info, ensure that there is "mcp_tokens" in the sly data
            # for the provider to use and update, otherwise just pass an empty dict.
            token = await self._prepare_token(server_url, sly_data)
        # Create and configure OAuth provider
        provider: OauthProviderFactory = await self._create_oauth_provider(server_url, client_info, token)

        return await provider.get_auth()

    async def get_mcp_tools(
        self,
        server_url: str,
        allowed_tools: Optional[List[str]],
        sly_data: Dict[str, Any]
    ) -> List[BaseTool]:
        """
        Fetches tools from the given MCP server and returns them as LangChain-compatible tools.

        The method handles:
        - OAuth authentication (client_credentials and refresh_token flows supported)
        - Putting env var values for client info and token to sly_data when available
        - Tool filtering based on allowed list
        - Automatic session management and cleanup

        :param server_url: URL of the MCP server, e.g. https://mcp.deepwiki.com/mcp or http://localhost:8000/mcp/
        :param allowed_tools: Optional list of tool names to filter from the server's available tools.
                              If None, uses server config tools or all tools from the server will be returned.
        :param sly_data: Optional dictionary of sly data (client info, token, headers) to use for MCP requests.

        :return: A list of LangChain BaseTool instances retrieved from the MCP server.
        """
        # Prepare MCP tool configuration
        mcp_tool_dict: Dict[str, Any] = {
            "url": server_url,
            "transport": "streamable_http",
        }

        # Add headers if available
        sly_data_headers: Dict[str, Any] = sly_data.get("http_headers", {}).get(server_url)
        # Prepare headers by prioritizing sly data over MCP server info file and validating format
        prepared_headers = await self._prepare_headers(server_url, sly_data_headers)
        if prepared_headers:
            mcp_tool_dict["headers"] = prepared_headers

        # Add auth if needed
        # Prepare auth by prioritizing sly data over env var client info and token and validating format
        # and store token from env var in sly data when used
        auth: Auth = await self._prepare_auth(server_url, sly_data)
        if auth:
            mcp_tool_dict["auth"] = auth

        try:
            # Create MCP client
            client = MultiServerMCPClient({"server": mcp_tool_dict})

            # Fetch tools from server
            # The get_tools() method uses `async with create_session(...)` internally,
            # which guarantees proper session cleanup even if errors occur.
            # See: https://github.com/langchain-ai/langchain-mcp-adapters/blob/main/langchain_mcp_adapters/tools.py#L164
            mcp_tools: List[BaseTool] = await client.get_tools()

        except (OAuthFlowError, OAuthTokenError) as auth_error:
            self.logger.error("Authentication failed for MCP server %s: %s", server_url, auth_error, exc_info=True)
            mcp_tools = []

        # Determine which tools are allowed
        client_allowed_tools = await self._determine_allowed_tools(server_url, allowed_tools)

        # Store for instance reference
        self.client_allowed_tools = client_allowed_tools

        # Filter and tag tools
        mcp_tools = await self._filter_and_tag_tools(mcp_tools, client_allowed_tools)

        return mcp_tools
