
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

from copy import deepcopy
from logging import Logger
from logging import getLogger

from langchain_core.tools.base import BaseTool

from leaf_common.logging.sensitive_logger import SensitiveLogger
from leaf_common.utils.exception_util import ExceptionUtil

from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.run_context.interfaces.agent_network_inspector import AgentNetworkInspector
from neuro_san.internals.run_context.interfaces.tool_caller import ToolCaller
from neuro_san.internals.run_context.langchain.core.langchain_openai_function_tool import LangChainOpenAIFunctionTool
from neuro_san.internals.run_context.langchain.mcp.langchain_mcp_adapter import LangChainMcpAdapter
from neuro_san.internals.run_context.utils.external_tool_adapter import ExternalToolAdapter
from neuro_san.internals.utils.external_agent_parsing import ExternalAgentParsing
from neuro_san.message.types.agent_message import AgentMessage


class BaseToolFactory:
    """
    Creates langchain BaseTools.
    """

    # Parameters substituted for an external agent whose front-man declares
    # none of its own. See ensure_external_parameters() for the full rationale.
    DEFAULT_EXTERNAL_PARAMETER_NAME: str = "inquiry"
    DEFAULT_EXTERNAL_PARAMETERS: Dict[str, Any] = {
        "type": "object",
        "properties": {
            DEFAULT_EXTERNAL_PARAMETER_NAME: {
                "type": "string",
                "description": "The request to send to this agent network."
            }
        },
        "required": [DEFAULT_EXTERNAL_PARAMETER_NAME]
    }

    # Class-level because BaseToolFactory instances are per-request: remembers
    # which external agents this process has already warned about synthesizing
    # parameters for, so the warning is not repeated on every request.
    # An agent later observed with declared parameters is removed again, so a
    # network that is fixed and then regresses warns anew - hocon files can be
    # edited and hot-reloaded without a server restart.
    synthesis_warned: Set[str] = set()

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
        # Exception messages can carry sensitive request data, so log them
        # through a SensitiveLogger, which respects the LEAF_LOG_SENSITIVE
        # env var setting.
        self.sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)

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
        except ValueError as exception:
            # Could not reach the server for the external agent, so tell about it
            message: str = f"Agent/tool {name} was unreachable. Not including it as a tool.\n"
            message += str(exception)
            await self.report_tool_exclusion(message)
            return None

        try:
            function_json = await self.ensure_external_parameters(function_json, name)
            return self.create_function_tool(function_json, name)
        except ValueError as exception:
            # The agent was reachable, but what it reported cannot be made into a tool.
            message: str = f"Agent/tool {name} reported an invalid function definition. " + \
                           "Not including it as a tool.\n"
            message += str(exception)
            await self.report_tool_exclusion(message)
            return None

    async def report_tool_exclusion(self, message: str):
        """
        Report to both the client journal and the server logs that a tool
        is being left out of the calling agent's tool list.

        :param message: The message describing which tool and why
        """
        agent_message = AgentMessage(content=message)
        await self.journal.write_message(agent_message)
        self.sensitive_logger.info(message)

    async def ensure_external_parameters(self, function_json: Dict[str, Any], name: str) -> Dict[str, Any]:
        """
        Guarantee that an external agent's function spec declares parameters.

        The tool-call arguments are the only message channel through which a
        calling agent passes its request to an external agent network
        (sly_data is a separate, opt-in channel for private data).
        An external front-man that declares no function.parameters would
        therefore be presented to the calling LLM as a zero-argument tool,
        which the LLM would invoke with an empty {} - and the external network
        would silently never receive the caller's request (issue #1228).

        Note this is external-tools-only on purpose: internal tools without
        parameters (e.g. no-argument coded tools) legitimately take no
        arguments and are left alone.

        :param function_json: The function spec reported by the external agent.
                    Can be None when the agent was unreachable.
        :param name: The name of the external agent, for reporting.
        :return: The function_json as-is when it already declares parameters,
                    otherwise a copy with DEFAULT_EXTERNAL_PARAMETERS substituted in.
        """
        if function_json is None:
            # Unreachable external agent. create_function_tool() reports this case.
            return None

        if function_json.get("description") is None:
            # A spec with no description fails verify_function_json() no matter
            # what parameters it has. Leave it alone so that validation reports
            # the real problem, instead of journaling a promise here that a
            # synthesized parameter will get the request through, immediately
            # followed by the tool being dropped.
            return function_json

        raw_parameters: Any = function_json.get("parameters")
        if raw_parameters is not None and not isinstance(raw_parameters, Dict):
            # Not a schema we can reason about, however truthy or falsy
            # (e.g. a string, a list, a boolean).
            # Let verify_function_json() report it as invalid.
            return function_json

        parameters: Dict[str, Any] = raw_parameters or {}
        properties: Dict[str, Any] = parameters.get("properties") or {}
        if properties:
            # The network declares its own parameters. Re-arm the synthesis
            # warning in case the network regresses later.
            BaseToolFactory.synthesis_warned.discard(name)
            return function_json

        # A parameters block carrying anything beyond an empty properties
        # declaration is a declared schema in an unsupported dialect
        # (e.g. additionalProperties, anyOf, $ref). Let verify_function_json()
        # report it rather than silently replacing the declared contract
        # with the synthesized one.
        if parameters and not {"type", "properties", "required"}.issuperset(parameters.keys()):
            return function_json

        if name not in BaseToolFactory.synthesis_warned:
            BaseToolFactory.synthesis_warned.add(name)
            message: str = (
                f"The front-man of external agent {name} declares no parameters "
                f"in its function definition, so a single required "
                f"'{self.DEFAULT_EXTERNAL_PARAMETER_NAME}' string parameter "
                "is being synthesized for it to receive the calling agent's request. "
                "To control what this agent network receives, declare at least one parameter "
                "in the function definition of its front-man."
            )
            agent_message = AgentMessage(content=message)
            await self.journal.write_message(agent_message)
            self.logger.warning(message)

        function_json = dict(function_json)
        function_json["parameters"] = deepcopy(self.DEFAULT_EXTERNAL_PARAMETERS)
        return function_json

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
        - **String**: A canonical MCP server URI (see
          https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization#canonical-server-uri).
          Must use http(s), no fragment, with "mcp" appearing either as a host label
          (e.g. "mcp.example.com") or as a path segment (e.g. "/mcp", "/mcp/free", "/server/mcp").
        - **Dictionary**:
            - "url" (str): MCP server URL.
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
            message += ExceptionUtil.get_exception_details(nested_exception)
            agent_message = AgentMessage(content=message)
            await self.journal.write_message(agent_message)
            self.sensitive_logger.info(message)
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
            self.sensitive_logger.warning(message)
            return None

    def create_function_tool(self, function_json: Dict[str, Any], name: str) -> BaseTool:
        """Create a function tool from JSON specification"""

        # In the case of external agents, if they report a name at all, they will
        # report something different that does not identify them as external.
        # Also, most internal agents do not have a name identifier on their functional
        # JSON, which is required.  Use the agent name we are using for look-up for that
        # regardless of intent.
        if function_json is None:
            # An external agent that responded without reporting a function has
            # no function_json. Raise ValueError so create_external_tool's
            # invalid-function-definition handler reports this instead of
            # the TypeError that the assignment below would otherwise raise.
            message: str = f"Could not create tool to call external agent '{name}'. Its function_json is None."
            raise ValueError(message)

        function_json["name"] = name
        return LangChainOpenAIFunctionTool.from_function_json(function_json, self.tool_caller)
