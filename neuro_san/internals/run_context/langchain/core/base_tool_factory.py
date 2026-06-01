
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
from typing import Set
from typing import Union

from logging import Logger
from logging import getLogger

from langchain_core.tools.base import BaseTool

from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.run_context.interfaces.agent_network_inspector import AgentNetworkInspector
from neuro_san.internals.run_context.interfaces.tool_caller import ToolCaller
from neuro_san.internals.run_context.langchain.core.langchain_openai_function_tool \
    import LangChainOpenAIFunctionTool
from neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter import LangChainMcpAdapter
from neuro_san.internals.run_context.utils.external_agent_parsing import ExternalAgentParsing
from neuro_san.internals.run_context.utils.external_tool_adapter import ExternalToolAdapter


class BaseToolFactory:
    """
    Creates langchain BaseTools.
    """

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def __init__(self,
                 tool_caller: ToolCaller,
                 invocation_context: InvocationContext,
                 journal: Journal):
        """
        Constructor

        :param tool_caller: The ToolCaller creating tools
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param journal: The journal to use when sending framework-level messages to the client
        """
        self.tool_caller: ToolCaller = tool_caller
        self.invocation_context: InvocationContext = invocation_context
        self.journal: Journal = journal
        self.logger: Logger = getLogger(self.__class__.__name__)

    async def create_base_tool(self, name: str) -> Union[BaseTool, List[BaseTool]]:
        """
        Create base tools for the agent to call.
        :param name: The name of the tool to create
        :return: The BaseTools associated with the name
        """

        # Check our own local inspector. Most tools live in the neighborhood.
        inspector: AgentNetworkInspector = self.tool_caller.get_inspector()
        agent_spec: Dict[str, Any] = inspector.get_agent_tool_spec(name)

        if agent_spec is None:
            return await self.create_external_tool(name)

        return await self.create_internal_tool(name, agent_spec)

    async def create_external_tool(self, name: Union[str, Dict[str, Any]]) -> Union[BaseTool, List[BaseTool]]:
        """
        Create external agent/tool.
        :param name: The name of the external agent/tool
        :return: External agent as base tools
        """

        if not isinstance(name, (dict, str)):
            raise TypeError(f"Tools must be string or dict, got {type(name)}")

        # Handle MCP-based tool as external tool
        if ExternalAgentParsing.is_mcp_tool(name):
            return await self.create_mcp_tool(name)

        # See if the agent name given could reference an external agent.
        if not ExternalAgentParsing.is_external_agent(name):
            return None

        # Use the ExternalToolAdapter to get the function specification
        # from the service call to the external agent.
        # We should be able to use the same BaseTool for langchain integration
        # purposes as we do for any other tool, though.
        # Optimization:
        #   It's possible we might want to cache these results somehow to minimize
        #   network calls.
        session_factory: AsyncAgentSessionFactory = self.invocation_context.get_async_session_factory()
        adapter = ExternalToolAdapter(session_factory, name)
        try:
            function_json: Dict[str, Any] = await adapter.get_function_json(self.invocation_context)
            return self.create_function_tool(function_json, name)
        except ValueError as exception:
            # Could not reach the server for the external agent, so tell about it
            message: str = f"Agent/tool {name} was unreachable. Not including it as a tool.\n"
            message += str(exception)
            agent_message = AgentMessage(content=message)
            await self.journal.write_message(agent_message)
            self.logger.info(message)
            return None

    async def create_internal_tool(self, name: str, agent_spec: Dict[str, Any]) -> BaseTool:
        """
        Create internal agent/tool.
        :param name: The name of the agent or coded tool
        :return: Agent as base tools
        """

        toolbox: str = agent_spec.get("toolbox")

        # Handle toolbox-based tools
        if toolbox:
            return await self.create_toolbox_tool(toolbox, agent_spec, name)

        # Handle coded tools
        function_json: Dict[str, Any] = agent_spec.get("function")
        if function_json is None:
            return None

        return self.create_function_tool(function_json, name)

    async def create_mcp_tool(self, mcp_info: Union[str, Dict[str, Any]]) -> List[BaseTool]:
        """
        Create MCP tools from the provided MCP configuration.

        The configuration can be one of:
        - **String**: A URL to an MCP server.
        Valid values start with "https://mcp" or end with "/mcp" or "/mcp/".
        - **Dictionary**:
            - "server" (str): MCP server URL.
            - "tools" (List[str], optional): List of tool names to allow from the server.

        :param mcp_info: MCP server URL (string) or a configuration dictionary
        :return: A list of MCP tools as base tools
        """
        # By default, assume no allowed tools. This may get updated below or in the LangChainMcpAdadter.
        allowed_tools: List[str] = None
        # Get HTTP headers from sly_data if available
        http_headers: Dict[str, Any] = self.tool_caller.get_sly_data().get("http_headers", {})

        if isinstance(mcp_info, str):
            server_url: str = mcp_info
        else:
            server_url = mcp_info.get("url")
            allowed_tools = mcp_info.get("tools")

        # Get specific headers for the MCP server if available
        headers: Dict[str, Any] = http_headers.get(server_url)

        try:
            mcp_adapter = LangChainMcpAdapter()
            mcp_tools: List[BaseTool] = await mcp_adapter.get_mcp_tools(server_url, allowed_tools, headers)

        # MCP errors are nested exceptions.
        except ExceptionGroup as nested_exception:
            # Could not reach the MCP server
            message: str = f"The URL {server_url} was unreachable. Not including it as a tool.\n"
            message += self.get_exception_details(nested_exception)
            agent_message = AgentMessage(content=message)
            await self.journal.write_message(agent_message)
            self.logger.info(message)
            return None

        # The allowed tools list might have been updated by the MCP adapter
        allowed_tools: List[str] = mcp_adapter.client_allowed_tools
        tool_names: List[str] = [tool.name for tool in mcp_tools]
        invalid_names: Set[str] = set(allowed_tools) - set(tool_names)
        # Check if there are invalid tool names in the list.
        if invalid_names:
            message = f"The following tools cannot be found in {server_url}: {invalid_names}"
            agent_message = AgentMessage(content=message)
            await self.journal.write_message(agent_message)
            self.logger.info(message)

        return mcp_tools

    def get_exception_details(self, exception, indent=0) -> str:
        """
        Recursively extract detailed information from nested exceptions.

        This function handles both regular exceptions and ExceptionGroup instances
        (introduced in Python 3.11) which can contain multiple nested exceptions.
        It creates a human-readable, hierarchical representation of all exceptions
        in the error chain.

        :param exception: The exception to analyze. Can be any Exception type,
                            including ExceptionGroup instances that contain multiple
                            nested exceptions.
        :parm indent: The current indentation level for formatting.
                                Each recursive call increases this by 1 to create
                                a visual hierarchy. Defaults to 0.

        :return: A formatted string containing the exception type, message, and
                any nested sub-exceptions with proper indentation to show the
                hierarchy. Each line ends with a newline character.

        Note:
            This function is particularly useful for debugging MCP (Model Context Protocol)
            errors and other complex exception scenarios where multiple errors can occur
            simultaneously and get wrapped in ExceptionGroup containers.
        """

        # Create indentation string based on current nesting level
        # Each level adds 2 spaces for visual hierarchy
        spaces: str = "  " * indent

        # Start building the message with exception type and description
        # Format: "ExceptionType: exception message"
        message: str = f"{spaces}{type(exception).__name__}: {exception}\n"

        # Check if this exception is an ExceptionGroup (Python 3.11+ feature)
        # ExceptionGroup can contain multiple exceptions that occurred simultaneously
        if isinstance(exception, ExceptionGroup):
            # Iterate through each sub-exception in the group
            for i, sub_exc in enumerate(exception.exceptions):
                # Add a header for each sub-exception with 1-based numbering
                message += f"{spaces}Sub-exception {i+1}:\n"

                # Recursively process the sub-exception with increased indentation
                # This handles cases where sub-exceptions might themselves be ExceptionGroups
                message += self.get_exception_details(sub_exc, indent + 1)

        return message

    async def create_toolbox_tool(self, toolbox: str, agent_spec: Dict[str, Any], name: str) -> BaseTool:
        """Create tool from toolbox"""

        toolbox_factory: ContextTypeToolboxFactory = self.invocation_context.get_toolbox_factory()
        try:
            tool_from_toolbox = toolbox_factory.create_tool_from_toolbox(toolbox, agent_spec.get("args"), name)
            # If the tool from toolbox is base tool or list of base tool, return the tool as is
            # since tool's definition and args schema are predefined in these the class of the tool.
            if isinstance(tool_from_toolbox, BaseTool) or (
                isinstance(tool_from_toolbox, list) and
                all(isinstance(tool, BaseTool) for tool in tool_from_toolbox)
            ):
                return tool_from_toolbox

            # Otherwise, it is a shared coded tool.
            return self.create_function_tool(tool_from_toolbox, name)

        except ValueError as tool_creation_exception:
            # There are errors in tool creation process
            message: str = f"Failed to create Agent/tool '{name}': {tool_creation_exception}"
            agent_message = AgentMessage(content=message)
            await self.journal.write_message(agent_message)
            self.logger.warning(message)
            return None

    def create_function_tool(self, function_json: Dict[str, Any], name: str) -> BaseTool:
        """Create a function tool from JSON specification"""

        # In the case of external agents, if they report a name at all, they will
        # report something different that does not identify them as external.
        # Also, most internal agents do not have a name identifier on their functional
        # JSON, which is required.  Use the agent name we are using for look-up for that
        # regardless of intent.
        if function_json is None:
            # An external agent that couldn't be reached has no function_json.
            # Raise ValueError so create_external_tool's existing handler turns this
            # into a user-facing "Agent/tool X was unreachable" message instead of
            # the TypeError that the assignment below would otherwise raise.
            message: str = f"Could not create tool to call external agent '{name}'. Its function_json is None."
            raise ValueError(message)

        function_json["name"] = name
        return LangChainOpenAIFunctionTool.from_function_json(function_json, self.tool_caller)
