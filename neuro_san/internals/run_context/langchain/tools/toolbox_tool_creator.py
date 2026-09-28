
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

from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.run_context.interfaces.tool_caller import ToolCaller
from neuro_san.internals.run_context.langchain.core.tool_spec_error import ToolSpecError
from neuro_san.internals.run_context.langchain.tools.function_tool_creator import FunctionToolCreator
from neuro_san.internals.run_context.langchain.tools.tool_creator import ToolCreator
from neuro_san.message.types.agent_message import AgentMessage


class ToolboxToolCreator(ToolCreator):
    """
    Creates the langchain BaseTool for an agent whose spec names a "toolbox"
    entry: a predefined langchain tool, or a shared coded tool whose function
    specification lives in the toolbox info file.
    """

    def __init__(self,
                 tool_caller: ToolCaller,
                 invocation_context: InvocationContext,
                 journal: Journal,
                 agent_location: str):
        """
        Constructor

        :param tool_caller: The ToolCaller the tools are created for
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param journal: The journal to use when sending framework-level messages to the client
        :param agent_location: Where a problem has to be fixed, in words a reader can act on
        """
        super().__init__(tool_caller, invocation_context, journal, agent_location)
        # A shared coded tool from the toolbox becomes an ordinary function tool.
        self.function_tool_creator: FunctionToolCreator = FunctionToolCreator(tool_caller, invocation_context,
                                                                              journal, agent_location)

    async def create(self, toolbox: str, agent_spec: Dict[str, Any], name: str) -> Union[BaseTool, List[BaseTool]]:
        """
        Create a tool from the toolbox.

        :param toolbox: The toolbox entry the agent spec refers to
        :param agent_spec: The agent's spec, whose "args" are passed to the toolbox tool
        :param name: The name of the agent
        :return: The BaseTool, or list of BaseTools, the toolbox entry defines; None when
                 the entry's spec is invalid or the tool could not be created. Both cases
                 are reported to the client journal.
        """

        toolbox_factory: ContextTypeToolboxFactory = self.invocation_context.get_toolbox_factory()
        try:
            tool_from_toolbox: Any = toolbox_factory.create_tool_from_toolbox(toolbox, agent_spec.get("args"), name)
            # If the tool from toolbox is base tool or list of base tool, return the tool as is
            # since tool's definition and args schema are predefined in these the class of the tool.
            if isinstance(tool_from_toolbox, BaseTool) or self._is_list_of_base_tools(tool_from_toolbox):
                return tool_from_toolbox

            # Otherwise, it is a shared coded tool.
            return self.function_tool_creator.create(tool_from_toolbox, name)

        except ToolSpecError as tool_spec_exception:
            # The toolbox entry itself was found, but its function spec could
            # not be turned into a tool.  Toolbox specs are not covered by the
            # registry-load validators, so this is the first place the problem
            # can be reported.
            message: str = f"Agent/tool '{name}' has an invalid function spec: {tool_spec_exception}"
            agent_message = AgentMessage(content=message)
            await self.journal.write_message(agent_message)
            self.sensitive_logger.warning(message)
            return None
        except ValueError as tool_creation_exception:
            # There are errors in tool creation process
            message: str = f"Failed to create Agent/tool '{name}': {tool_creation_exception}"
            agent_message = AgentMessage(content=message)
            await self.journal.write_message(agent_message)
            self.sensitive_logger.warning(message)
            return None

    @staticmethod
    def _is_list_of_base_tools(value: Any) -> bool:
        """
        Checks that a toolbox factory result is a list whose every element is a BaseTool.

        :param value: What the toolbox factory returned
        :return: True if value is a list whose every element is a BaseTool
        """
        if not isinstance(value, list):
            return False
        for tool in value:
            if not isinstance(tool, BaseTool):
                return False
        return True
