
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
from typing import Set

from copy import deepcopy

from typing_extensions import override

from langchain_core.tools.base import BaseTool

from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.run_context.langchain.tools.function_tool_creator import FunctionToolCreator
from neuro_san.internals.run_context.langchain.tools.tool_creator import ToolCreator
from neuro_san.internals.run_context.utils.external_tool_adapter import ExternalToolAdapter
from neuro_san.internals.utils.external_agent_parsing import ExternalAgentParsing
from neuro_san.message.types.agent_message import AgentMessage


class ExternalAgentToolCreator(ToolCreator):
    """
    Creates the langchain BaseTool through which an agent calls an external
    agent network: a "/name" reference to a network on the same server, or a
    URL reference to a network on another neuro-san server.

    The external network's front-man reports its function specification, and
    this class turns that into a tool. Its one piece of policy is
    ensure_external_parameters(): a front-man that declares no parameters gets
    a single "inquiry" parameter synthesized, so the caller's request has a
    channel to travel through.
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

    # Class-level because a creator lives for one tool reference of one
    # request: remembers which external agents this process has already
    # warned about synthesizing parameters for, so the warning is not
    # repeated on every request.
    # An agent later observed with declared parameters is removed again, so a
    # network that is fixed and then regresses warns anew - hocon files can be
    # edited and hot-reloaded without a server restart.
    synthesis_warned: Set[str] = set()

    @override
    async def create_tool(self, tool_name: str) -> BaseTool:
        """
        Create the tool for an external agent network.

        :param tool_name: The reference to the external agent, "/name" or a URL
        :return: The BaseTool for the external agent, or None when the reference is not
                 an external agent, the agent was unreachable, or what it reported
                 cannot be made into a tool. The last two cases are reported to the
                 client journal.
        """

        # See if the agent name given could reference an external agent.
        if not ExternalAgentParsing.is_external_agent(tool_name):
            return None

        # Use the ExternalToolAdapter to get the function specification
        # from the service call to the external agent.
        # We should be able to use the same BaseTool for langchain integration
        # purposes as we do for any other tool, though.
        # Optimization:
        #   It's possible we might want to cache these results somehow to minimize
        #   network calls.
        session_factory: AsyncAgentSessionFactory = self.invocation_context.get_async_session_factory()
        adapter = ExternalToolAdapter(session_factory, tool_name)
        function_json: Dict[str, Any] = None
        try:
            function_json = await adapter.get_function_json(self.invocation_context)
        except ValueError as exception:
            # Could not reach the server for the external agent, so tell about it
            message: str = f"Agent/tool {tool_name} was unreachable. Not including it as a tool.\n"
            message += str(exception)
            await self.report_tool_exclusion(message)
            return None

        try:
            use_function_json: Dict[str, Any] = await self.ensure_external_parameters(function_json, tool_name)
            function_tool_creator: FunctionToolCreator = FunctionToolCreator(
                self.tool_caller, self.invocation_context, self.journal, self.agent_location, use_function_json)
            return await function_tool_creator.create_tool(tool_name)
        except ValueError as exception:
            # The agent was reachable, but what it reported cannot be made into a tool.
            message: str = f"Agent/tool {tool_name} reported an invalid function definition. " + \
                           "Not including it as a tool.\n"
            message += str(exception)
            await self.report_tool_exclusion(message)
            return None

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
            # Unreachable external agent. FunctionToolCreator.create_tool() reports this case.
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
            ExternalAgentToolCreator.synthesis_warned.discard(name)
            return function_json

        # A parameters block carrying anything beyond an empty properties
        # declaration is a declared schema in an unsupported dialect
        # (e.g. additionalProperties, anyOf, $ref). Let verify_function_json()
        # report it rather than silently replacing the declared contract
        # with the synthesized one.
        if parameters and not {"type", "properties", "required"}.issuperset(parameters.keys()):
            return function_json

        if name not in ExternalAgentToolCreator.synthesis_warned:
            ExternalAgentToolCreator.synthesis_warned.add(name)
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

        use_function_json: Dict[str, Any] = dict(function_json)
        use_function_json["parameters"] = deepcopy(self.DEFAULT_EXTERNAL_PARAMETERS)
        return use_function_json
