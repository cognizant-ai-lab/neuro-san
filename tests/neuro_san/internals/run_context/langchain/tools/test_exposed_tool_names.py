
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
from typing import Set

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from langchain_core.tools import StructuredTool

from neuro_san.internals.run_context.langchain.tools.exposed_tool_names import ExposedToolNames
from neuro_san.message.types.agent_message import AgentMessage


class TestExposedToolNames(IsolatedAsyncioTestCase):
    """
    Unit tests for ExposedToolNames, the cross-kind record of tool names an
    agent has exposed so far.
    """

    AGENT_LOCATION: str = "agent 'researcher' of agent network 'deep/math_guy'"

    @staticmethod
    def make_named_tool(name: str) -> MagicMock:
        """
        Builds a StructuredTool-shaped mock with the given name.

        :param name: The exposed tool name
        :return: A StructuredTool-shaped mock carrying that name
        """
        tool = MagicMock(spec=StructuredTool)
        tool.name = name
        return tool

    def make_names(self) -> ExposedToolNames:
        """
        Builds the record under test with a mocked journal.

        :return: An ExposedToolNames with a mocked journal
        """
        journal = MagicMock()
        journal.write_message = AsyncMock()
        return ExposedToolNames(journal, self.AGENT_LOCATION)

    async def test_repeated_name_is_reported_but_kept(self) -> None:
        """
        A coded or internal tool that repeats an exposed name is reported in the
        journal but not dropped, since dropping it would change behaviour that
        predates the name check.
        """
        names: ExposedToolNames = self.make_names()

        await names.remember(self.make_named_tool("search"))
        await names.remember([self.make_named_tool("search"), self.make_named_tool("lookup")])

        self.assertEqual(names.get_names(), {"search", "lookup"})
        names.journal.write_message.assert_awaited_once()
        reported: AgentMessage = names.journal.write_message.await_args.args[0]
        expected_start: str = f"{self.AGENT_LOCATION}: tool 'search' has the same name as another tool"
        self.assertTrue(reported.content.startswith(expected_start), reported.content)
        self.assertIn("hocon file", reported.content)

    async def test_none_and_empty_results_are_ignored(self) -> None:
        """
        A creator that produced nothing, None or an empty list, adds no names
        and journals nothing.
        """
        names: ExposedToolNames = self.make_names()

        await names.remember(None)
        await names.remember([])

        self.assertEqual(names.get_names(), set())
        names.journal.write_message.assert_not_awaited()

    async def test_is_taken_and_get_names_copy(self) -> None:
        """
        is_taken() answers for names remembered so far, and get_names() hands
        out a copy, so a caller cannot change the record by accident.
        """
        names: ExposedToolNames = self.make_names()
        await names.remember(self.make_named_tool("a__b"))

        self.assertTrue(names.is_taken("a__b"))
        self.assertFalse(names.is_taken("other"))

        copy: Set[str] = names.get_names()
        copy.add("other")
        self.assertFalse(names.is_taken("other"))
