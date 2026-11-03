
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
from typing import Union

from langchain_core.tools.base import BaseTool

from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.run_context.interfaces.agent_network_inspector import AgentNetworkInspector
from neuro_san.internals.run_context.interfaces.tool_caller import ToolCaller
from neuro_san.internals.run_context.langchain.tools.exposed_tool_names import ExposedToolNames
from neuro_san.internals.run_context.langchain.tools.external_agent_tool_creator import ExternalAgentToolCreator
from neuro_san.internals.run_context.langchain.tools.function_tool_creator import FunctionToolCreator
from neuro_san.internals.run_context.langchain.tools.mcp_tool_creator import McpToolCreator
from neuro_san.internals.run_context.langchain.tools.tool_creator import ToolCreator
from neuro_san.internals.run_context.langchain.tools.toolbox_tool_creator import ToolboxToolCreator
from neuro_san.internals.utils.external_agent_parsing import ExternalAgentParsing


class BaseToolFactory:
    """
    Creates langchain BaseTools for the tools an agent lists.

    This class only decides which kind of tool a reference is and builds the
    creator for that kind, all in the tools package: FunctionToolCreator
    for coded tools and internal agents, ToolboxToolCreator for toolbox
    entries, ExternalAgentToolCreator for other agent networks, and
    McpToolCreator for MCP servers. A creator is built for one reference,
    with what its kind needs in its constructor, and every creator is then
    called the same way: create_tool(tool_name). Each creator owns the policy
    for its kind.
    The one thing kept across kinds is ExposedToolNames, so that a later tool
    repeating a name is caught whatever kind either tool is.
    """

    def __init__(self,
                 tool_caller: ToolCaller,
                 invocation_context: InvocationContext,
                 journal: Journal) -> None:
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
        # Where a problem has to be fixed: the agent whose "tools" list is being
        # built and the network, hence the hocon file, it lives in. Every message
        # for the user starts with it, so nobody has to guess which file to open.
        # The network name comes from the inspector, not the invocation context:
        # the context carries the network the client asked for, and it is copied
        # unchanged when an agent calls another network on the same server, so
        # inside that network it would name the caller's hocon file.
        inspector: AgentNetworkInspector = tool_caller.get_inspector()
        self.agent_location: str = (f"agent '{tool_caller.get_name()}' of agent network "
                                    f"'{inspector.get_network_name()}'")
        # Shared across every kind of tool, so the MCP creator can see names
        # that coded tools or other servers already took.
        self.exposed_tool_names: ExposedToolNames = ExposedToolNames(journal, self.agent_location)

    async def create_base_tool(self, name: Union[str, Dict[str, Any]]) -> Union[BaseTool, List[BaseTool]]:
        """
        Create base tools for the agent to call.

        :param name: One entry of the agent's "tools" list: the name of an agent or
                     coded tool of this network, an external agent reference, or an
                     MCP server reference, which may be a dictionary
        :return: The BaseTools associated with the name
        """

        # Check our own local inspector. Most tools live in the neighborhood.
        inspector: AgentNetworkInspector = self.tool_caller.get_inspector()
        agent_spec: Dict[str, Any] = inspector.get_agent_tool_spec(name)

        created: Union[BaseTool, List[BaseTool]] = None
        if agent_spec is None:
            created = await self.create_external_tool(name)
        else:
            created = await self.create_internal_tool(name, agent_spec)

        await self.exposed_tool_names.remember(created)
        return created

    async def create_internal_tool(self, name: str, agent_spec: Dict[str, Any]) -> Union[BaseTool, List[BaseTool]]:
        """
        Create the tool for an agent or coded tool of this agent network.

        :param name: The name of the agent or coded tool
        :param agent_spec: Its spec from the network's registry
        :return: The tool from the toolbox when the spec names one, otherwise the
                 function tool for the spec's "function"; None when the spec has neither.
        """

        creator: ToolCreator = None
        if agent_spec.get("toolbox"):
            # Handle toolbox-based tools
            creator = ToolboxToolCreator(self.tool_caller, self.invocation_context, self.journal,
                                         self.agent_location, agent_spec)
        else:
            # Handle coded tools
            function_json: Dict[str, Any] = agent_spec.get("function")
            if function_json is None:
                return None
            creator = FunctionToolCreator(self.tool_caller, self.invocation_context, self.journal,
                                          self.agent_location, function_json)

        return await creator.create_tool(name)

    async def create_external_tool(self, name: Union[str, Dict[str, Any]]) -> Union[BaseTool, List[BaseTool]]:
        """
        Create the tool(s) for a reference that names nothing in this agent
        network: an MCP server, or an external agent network.

        :param name: The reference: a string, or a dictionary MCP reference
        :return: The MCP server's tools, the external agent's tool, or None when
                 the reference is neither
        :raises TypeError: When the reference is neither a string nor a dictionary
        """

        if not isinstance(name, (dict, str)):
            raise TypeError(f"Tools must be string or dict, got {type(name)}")

        creator: ToolCreator = None
        if ExternalAgentParsing.is_mcp_tool(name):
            # An MCP reference is the server URL alone, or a dictionary with the
            # URL under "url" and an optional allow list of tool names under "tools".
            server_url: str = None
            allowed_tools: List[str] = None
            if isinstance(name, dict):
                server_url = name.get("url")
                allowed_tools = name.get("tools")
            else:
                server_url = name
            creator = McpToolCreator(self.tool_caller, self.invocation_context, self.journal,
                                     self.agent_location, self.exposed_tool_names, allowed_tools)
            return await creator.create_tool(server_url)

        creator = ExternalAgentToolCreator(self.tool_caller, self.invocation_context, self.journal,
                                           self.agent_location)
        return await creator.create_tool(name)
