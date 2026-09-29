
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

from typing_extensions import override

from langchain_core.tools.base import BaseTool

from leaf_common.utils.exception_util import ExceptionUtil

from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.run_context.interfaces.tool_caller import ToolCaller
from neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter import LangChainMcpAdapter
from neuro_san.internals.run_context.langchain.tools.exposed_tool_names import ExposedToolNames
from neuro_san.internals.run_context.langchain.tools.tool_creator import ToolCreator
from neuro_san.message.types.agent_message import AgentMessage


class McpToolCreator(ToolCreator):
    """
    Creates the langchain BaseTools through which an agent calls the tools of
    one MCP server named in the agent's "tools" list, by URL alone or with an
    allow list of tool names.

    LangChainMcpAdapter fetches the server's tools, applies the allow list and
    renames provider-unsafe names within that one server. The policy that
    remains here is what only the caller can know: which allow-list entries
    matched nothing, and which exposed names an earlier tool of this agent,
    from another server or of another kind, already uses.
    """

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def __init__(self,
                 tool_caller: ToolCaller,
                 invocation_context: InvocationContext,
                 journal: Journal,
                 agent_location: str,
                 exposed_tool_names: ExposedToolNames,
                 allowed_tools: List[str] = None) -> None:
        """
        Constructor

        :param tool_caller: The ToolCaller the tools are created for
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param journal: The journal to use when sending framework-level messages to the client
        :param agent_location: Where a problem has to be fixed, in words a reader can act on
        :param exposed_tool_names: The names already exposed by this agent's other tools
        :param allowed_tools: The "tools" allow list of a dictionary reference. None for a
                    reference by URL alone, so the adapter applies its own defaults.
        """
        super().__init__(tool_caller, invocation_context, journal, agent_location)
        self.exposed_tool_names: ExposedToolNames = exposed_tool_names
        self.allowed_tools: List[str] = allowed_tools

    @override
    async def create_tool(self, tool_name: str) -> List[BaseTool]:
        """
        Create the tools of one MCP server.

        :param tool_name: The MCP server URL: a canonical MCP server URI (see
                    https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization#canonical-server-uri)
                    over http(s), with no fragment, and with "mcp" as a host label
                    (e.g. "mcp.example.com") or a path segment (e.g. "/mcp", "/mcp/free", "/server/mcp").
        :return: A list of MCP tools as base tools, or None when the server was unreachable
        """
        server_url: str = tool_name
        # Get HTTP headers from sly_data if available
        http_headers: Dict[str, Any] = self.tool_caller.get_sly_data().get("http_headers", {})
        # Get specific headers for the MCP server if available
        headers: Dict[str, Any] = http_headers.get(server_url)

        mcp_adapter: LangChainMcpAdapter = None
        mcp_tools: List[BaseTool] = None
        try:
            mcp_adapter = LangChainMcpAdapter(self.agent_location)
            mcp_tools = await mcp_adapter.get_mcp_tools(server_url, self.allowed_tools, headers)

        # MCP errors are nested exceptions.
        except ExceptionGroup as nested_exception:
            # Could not reach the MCP server
            message: str = f"{self.agent_location}: the URL {server_url} was unreachable. Not including it as a tool.\n"
            message += ExceptionUtil.get_exception_details(nested_exception)
            await self.report_tool_exclusion(message)
            return None

        # The adapter matches allow-list entries against the names the server
        # advertised, in either spelling, and then renames tools for the LLM
        # ("deep/math_guy" is exposed as "deep__math_guy"). Comparing the entries
        # with the exposed names here would report a tool that was found, so ask
        # the adapter which entries really matched nothing.
        invalid_names: List[str] = mcp_adapter.get_unmatched_allowed_tools()
        if invalid_names:
            message = f"{self.agent_location}: the following tools cannot be found in {server_url}: {invalid_names}"
            agent_message = AgentMessage(content=message)
            await self.journal.write_message(agent_message)
            self.logger.info(message)

        return await self._skip_tools_already_named(server_url, mcp_tools)

    async def _skip_tools_already_named(self, server_url: str, mcp_tools: List[BaseTool]) -> List[BaseTool]:
        """
        Drops MCP tools whose exposed name an earlier tool of this agent already
        uses. The record is per agent, so another agent may expose the same name.

        LangChainMcpAdapter resolves name collisions within one server only. Two
        servers, or a server and a coded tool, can still expose one name, for
        example "a/b" renamed to "a__b" on one server and a literal "a__b" on
        another. The first tool to claim a name keeps it, in the order of the
        agent's "tools" list.

        :param server_url: URL of the MCP server the tools came from, for messages.
        :param mcp_tools: The tools the adapter returned for that server.
        :return: The tools whose names are not yet exposed, in the same order.
        """
        kept_tools: List[BaseTool] = []
        for tool in mcp_tools:
            if self.exposed_tool_names.is_taken(tool.name):
                message: str = (f"{self.agent_location}: MCP tool '{tool.name}' from {server_url} has the same name as "
                                "a tool already in this agent's tool list; skipping it. Rename one of them, or "
                                "narrow the \"tools\" allow list under this server in the agent's hocon file.")
                await self.journal.write_message(AgentMessage(content=message))
                self.logger.warning(message)
                continue
            kept_tools.append(tool)
        return kept_tools
