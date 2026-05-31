
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

import copy
from logging import Logger
from logging import getLogger
import threading

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from neuro_san.internals.run_context.langchain.mcp.mcp_servers_info_restorer import McpServersInfoRestorer


class LangChainMcpAdapter:
    """
    Adapter class to fetch tools from a Multi-Client Protocol (MCP) server and return them as
    LangChain-compatible tools. This class provides static methods for interacting with MCP servers.
    """

    _mcp_info_lock: threading.Lock = threading.Lock()
    _mcp_servers_info: Dict[str, Any] = None

    def __init__(self):
        """
        Constructor
        """
        self.client_allowed_tools: List[str] = []
        self.logger: Logger = getLogger(self.__class__.__name__)

    def _load_mcp_servers_info(self):
        """
        Loads MCP servers information from a configuration file if not already loaded.
        """
        # Write through the class so the cache stays shared across instances.
        # `self._mcp_servers_info = ...` would create an instance attribute that shadows
        # the class attribute, leaving the class-level cache stuck at None and causing
        # every new LangChainMcpAdapter to reload (and re-log) the config.
        with LangChainMcpAdapter._mcp_info_lock:
            if LangChainMcpAdapter._mcp_servers_info is None:
                try:
                    LangChainMcpAdapter._mcp_servers_info = McpServersInfoRestorer().restore()
                except ValueError as value_error:
                    self.logger.warning("Error occurred while loading MCP servers info: %s", value_error)
                    self.logger.info("Proceeding with empty MCP servers info.")
                if LangChainMcpAdapter._mcp_servers_info is None:
                    # Something went wrong reading the file.
                    # Prevent further attempts to load info.
                    LangChainMcpAdapter._mcp_servers_info = {}

    async def get_mcp_tools(
            self,
            server_url: str,
            allowed_tools: Optional[List[str]] = None,
            headers: Optional[Dict[str, Any]] = None
    ) -> List[BaseTool]:
        """
        Fetches tools from the given MCP server and returns them as a list of LangChain-compatible tools.

        :param server_url: URL of the MCP server, e.g. https://mcp.deepwiki.com/mcp or http://localhost:8000/mcp/
        :param allowed_tools: Optional list of tool names to filter from the server's available tools.
                              If None, all tools from the server will be returned.
        :param headers: Optional dictionary of HTTP headers to include in the MCP requests.

        :return: A list of LangChain BaseTool instances retrieved from the MCP server.
        """
        if self._mcp_servers_info is None:
            self._load_mcp_servers_info()

        mcp_tool_dict: Dict[str, Any] = {
            "url": server_url,
            "transport": "streamable_http",
        }
        # Try to look up authentication details first from the sly data then from the MCP servers info.
        headers_dict: Dict[str, Any] = headers or self._mcp_servers_info.get(server_url, {}).get("http_headers")
        if headers_dict:
            if isinstance(headers_dict, dict):
                # Use a copy to avoid modifying the original headers dictionary.
                mcp_tool_dict["headers"] = copy.copy(headers_dict)
            else:
                self.logger.error("MCP client headers for server %s must be a dictionary.",  server_url)

        client = MultiServerMCPClient(
            {"server": mcp_tool_dict}
        )

        # The get_tools() method returns a list of StructuredTool instances, which are subclasses of BaseTool.
        # Internally, it calls load_mcp_tools(), which uses an `async with create_session(...)` block.
        # This guarantees that any temporary MCP session created is properly closed when the block exits,
        # even if an error is raised during tool loading.
        # See: https://github.com/langchain-ai/langchain-mcp-adapters/blob/main/langchain_mcp_adapters/tools.py#L164
        # Optimization:
        #   It's possible we might want to cache these results somehow to minimize tool calls.
        mcp_tools: List[BaseTool] = await client.get_tools()

        # If allowed_tools is provided, filter the list to include only those tools.
        client_allowed_tools: List[str] = allowed_tools
        if client_allowed_tools is None:
            # Check if MCP server info has a "tools" field to use as allowed tools.
            client_allowed_tools = self._mcp_servers_info.get(server_url, {}).get("tools", [])
        # If client allowed tools is an empty list, do not filter the tools.
        if client_allowed_tools:
            mcp_tools = [tool for tool in mcp_tools if tool.name in client_allowed_tools]

        self.client_allowed_tools = client_allowed_tools

        for tool in mcp_tools:
            # Add "langchain_tool" tags so journal callback can idenitify it.
            # These MCP tools are treated as Langchain tools and can be reported in the thinking file.
            tool.tags = ["langchain_tool"]

        return mcp_tools
