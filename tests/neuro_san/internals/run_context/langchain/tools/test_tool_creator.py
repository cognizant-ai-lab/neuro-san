
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
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from neuro_san.internals.run_context.langchain.tools.function_tool_creator import FunctionToolCreator
from neuro_san.internals.run_context.langchain.tools.tool_creator import ToolCreator
from neuro_san.message.types.agent_message import AgentMessage


class TestToolCreator(IsolatedAsyncioTestCase):
    """
    Unit tests for ToolCreator, the state and reporting shared by every
    tool creator.
    """

    AGENT_LOCATION: str = "agent 'researcher' of agent network 'deep/math_guy'"

    async def test_report_tool_exclusion_journals_and_logs(self) -> None:
        """
        An exclusion report reaches the client through the journal and the
        server through the sensitive logger, which may hold request data.
        """
        journal = MagicMock()
        journal.write_message = AsyncMock()
        creator: ToolCreator = ToolCreator(MagicMock(), MagicMock(), journal, self.AGENT_LOCATION)
        creator.sensitive_logger = MagicMock()

        await creator.report_tool_exclusion("Agent/tool /x was unreachable.")

        journal.write_message.assert_awaited_once()
        reported: AgentMessage = journal.write_message.await_args.args[0]
        self.assertEqual(reported.content, "Agent/tool /x was unreachable.")
        creator.sensitive_logger.info.assert_called_once_with("Agent/tool /x was unreachable.")

    def test_logger_is_named_after_the_concrete_class(self) -> None:
        """
        Each creator logs under its own class name, so a log line says which
        kind of tool it is about.
        """
        creator: FunctionToolCreator = FunctionToolCreator(MagicMock(), MagicMock(), MagicMock(), self.AGENT_LOCATION)

        self.assertEqual(creator.logger.name, "FunctionToolCreator")
        self.assertEqual(creator.agent_location, self.AGENT_LOCATION)
