
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
from neuro_san.internals.run_context.langchain.tools.toolbox_tool_creator import ToolboxToolCreator
from neuro_san.internals.utils.external_agent_parsing import ExternalAgentParsing


class BaseToolFactory:
    """
    Creates langchain BaseTools for the tools an agent lists.

    This class only decides which kind of tool a reference is and hands it to
    the creator for that kind, all in the tools package: FunctionToolCreator
    for coded tools and internal agents, ToolboxToolCreator for toolbox
    entries, ExternalAgentToolCreator for other agent networks, and
    McpToolCreator for MCP servers. Each creator owns the policy for its kind.
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
        self.function_tool_creator: FunctionToolCreator = FunctionToolCreator(
            tool_caller, invocation_context, journal, self.agent_location)
        self.toolbox_tool_creator: ToolboxToolCreator = ToolboxToolCreator(
            tool_caller, invocation_context, journal, self.agent_location)
        self.external_agent_tool_creator: ExternalAgentToolCreator = ExternalAgentToolCreator(
            tool_caller, invocation_context, journal, self.agent_location)
        self.mcp_tool_creator: McpToolCreator = McpToolCreator(
            tool_caller, invocation_context, journal, self.agent_location, self.exposed_tool_names)

    async def create_base_tool(self, name: str) -> Union[BaseTool, List[BaseTool]]:
        """
        Create base tools for the agent to call.

        :param name: The name of the tool to create
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

        toolbox: str = agent_spec.get("toolbox")

        # Handle toolbox-based tools
        if toolbox:
            return await self.toolbox_tool_creator.create(toolbox, agent_spec, name)

        # Handle coded tools
        function_json: Dict[str, Any] = agent_spec.get("function")
        if function_json is None:
            return None

        return self.function_tool_creator.create(function_json, name)

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

        # Handle MCP-based tool as external tool
        if ExternalAgentParsing.is_mcp_tool(name):
            return await self.mcp_tool_creator.create(name)

        return await self.external_agent_tool_creator.create(name)
