
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from typing import List
from typing import Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient


class LangChainMcpAdapter:
    """
    Adapter class to fetch tools from a Multi-Client Protocol (MCP) server and return them as
    LangChain-compatible tools. This class provides static methods for interacting with MCP servers.
    """

    @staticmethod
    async def get_mcp_tools(
        server_url: str,
        allowed_tools: Optional[List[str]] = None,
    ) -> List[BaseTool]:
        """
        Fetches tools from the given MCP server and returns them as a list of LangChain-compatible tools.

        :param server_url: URL of the MCP server, e.g. https://mcp.deepwiki.com/mcp or http://localhost:8000/mcp/
        :param allowed_tools: Optional list of tool names to filter from the server's available tools.
                              If None, all tools from the server will be returned.

        :return: A list of LangChain BaseTool instances retrieved from the MCP server.
        """

        client = MultiServerMCPClient(
            {
                "mcp_tool": {
                    "url": server_url,
                    "transport": "streamable_http",
                    # As of 09/22/2025, Neuro-SAN does not support passing authentication
                    # details (e.g., tokens) through the HOCON interface.
                    # In the future, these details will be provided in the "headers" key here.
                }
            }
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
        if allowed_tools:
            mcp_tools = [tool for tool in mcp_tools if tool.name in allowed_tools]

        for tool in mcp_tools:
            # Add "langchain_tool" tags so journal callback can idenitify it.
            # Thus MCP tools are treated as Langchain tools and can be reported in the thinking file.
            tool.tags = ["langchain_tool"]

        return mcp_tools
