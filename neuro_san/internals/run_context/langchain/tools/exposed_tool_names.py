
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
from typing import Set
from typing import Union

from logging import Logger
from logging import getLogger

from langchain_core.tools.base import BaseTool

from neuro_san.internals.journals.journal import Journal
from neuro_san.message.types.agent_message import AgentMessage


class ExposedToolNames:
    """
    The names of the tools created so far for one agent, across every kind of
    tool, so that a later tool that would expose the same name is caught.

    LangChain dispatches tool calls by name, so two tools under one name would
    leave the LLM's call ambiguous. This state spans tool kinds, which is why it
    lives here rather than in any one tool creator: McpToolCreator asks it
    whether a name is taken before exposing an MCP tool, and BaseToolFactory
    records every created tool through it.
    """

    def __init__(self, journal: Journal, agent_location: str):
        """
        Constructor

        :param journal: The journal to use when sending framework-level messages to the client
        :param agent_location: Where a problem has to be fixed, in words a reader can act on,
                    for example "agent 'researcher' of agent network 'deep/math_guy'".
        """
        self.journal: Journal = journal
        self.agent_location: str = agent_location
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.names: Set[str] = set()

    def get_names(self) -> Set[str]:
        """
        Snapshot of the tool names exposed so far.

        :return: A copy of the names exposed so far
        """
        return set(self.names)

    def is_taken(self, name: str) -> bool:
        """
        Tells whether a tool of this agent already uses a name.

        :param name: A tool name about to be exposed
        :return: True if a tool of this agent already uses the name
        """
        return name in self.names

    async def remember(self, created: Union[BaseTool, List[BaseTool]]) -> None:
        """
        Records the names of newly created tools and reports any that repeat a
        name already exposed in this agent network.

        MCP tools that repeat a name never get here: McpToolCreator drops
        them. Any other repeat is only reported, since dropping a coded or
        internal tool would change behaviour that predates the name check.

        :param created: What a creator produced: a tool, a list of tools, or None.
        """
        tools: List[BaseTool] = []
        if isinstance(created, list):
            tools = created
        elif created is not None:
            tools = [created]

        for tool in tools:
            if self.is_taken(tool.name):
                message: str = (f"{self.agent_location}: tool '{tool.name}' has the same name as another tool of "
                                "this agent; the LLM cannot tell them apart. Rename one of them, or drop one "
                                "from the agent's \"tools\" list in its hocon file.")
                await self.journal.write_message(AgentMessage(content=message))
                self.logger.warning(message)
            self.names.add(tool.name)
