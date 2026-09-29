
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
from typing import List
from typing import Union

from logging import Logger
from logging import getLogger

from langchain_core.tools.base import BaseTool

from leaf_common.logging.sensitive_logger import SensitiveLogger

from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.run_context.interfaces.tool_caller import ToolCaller
from neuro_san.message.types.agent_message import AgentMessage


class ToolCreator:
    """
    Common state and reporting for the classes that each create one kind of
    langchain BaseTool for an agent: function (coded) tools, toolbox tools,
    external agents and MCP servers.

    BaseToolFactory decides which creator a tool reference goes to and builds
    one creator for that reference. Whatever a kind needs beyond the tool's
    name is given to its constructor, so every creator is called the same
    way: create_tool(name). Each creator owns the policy for its own kind, so
    that policy and its tests live next to the code they are about.
    """

    def __init__(self,
                 tool_caller: ToolCaller,
                 invocation_context: InvocationContext,
                 journal: Journal,
                 agent_location: str) -> None:
        """
        Constructor

        :param tool_caller: The ToolCaller the tools are created for
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param journal: The journal to use when sending framework-level messages to the client
        :param agent_location: Where a problem has to be fixed, in words a reader can act on,
                    for example "agent 'researcher' of agent network 'deep/math_guy'".
                    Messages start with it so nobody has to guess which hocon file to open.
        """
        self.tool_caller: ToolCaller = tool_caller
        self.invocation_context: InvocationContext = invocation_context
        self.journal: Journal = journal
        self.agent_location: str = agent_location
        self.logger: Logger = getLogger(self.__class__.__name__)
        # Exception messages can carry sensitive request data, so log them
        # through a SensitiveLogger, which respects the LEAF_LOG_SENSITIVE
        # env var setting.
        self.sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)

    async def create_tool(self, name: str) -> Union[BaseTool, List[BaseTool]]:
        """
        Create the tool, or tools, for one entry of the agent's "tools" list.

        :param name: The name the calling agent uses to look the tool up
        :return: The BaseTool, or list of BaseTools, for the name. None when no
                 tool can be made, which the creator reports to the client journal.
        :raises NotImplementedError: When a subclass does not implement it
        """
        raise NotImplementedError

    async def report_tool_exclusion(self, message: str) -> None:
        """
        Report to both the client journal and the server logs that a tool
        is being left out of the calling agent's tool list.

        :param message: The message describing which tool and why
        """
        agent_message = AgentMessage(content=message)
        await self.journal.write_message(agent_message)
        self.sensitive_logger.info(message)
