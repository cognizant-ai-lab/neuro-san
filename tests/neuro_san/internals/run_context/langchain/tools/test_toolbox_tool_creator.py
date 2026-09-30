
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

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from langchain_core.tools import BaseTool

from neuro_san.internals.run_context.langchain.core.tool_spec_error import ToolSpecError
from neuro_san.internals.run_context.langchain.tools.toolbox_tool_creator import ToolboxToolCreator
from neuro_san.message.types.agent_message import AgentMessage


class TestToolboxToolCreator(IsolatedAsyncioTestCase):
    """
    Unit tests for ToolboxToolCreator: what comes back from the toolbox
    factory is passed through, turned into a function tool, or reported.
    """

    AGENT_LOCATION: str = "agent 'researcher' of agent network 'deep/math_guy'"
    AGENT_SPEC: Dict[str, Any] = {"toolbox": "web_search", "args": {"depth": 2}}

    def make_creator(self, tool_from_toolbox: Any = None, error: Exception = None) -> ToolboxToolCreator:
        """
        Builds a creator for AGENT_SPEC whose toolbox factory returns, or raises, what the test needs.

        :param tool_from_toolbox: What the toolbox factory should return
        :param error: What the toolbox factory should raise instead, if anything
        :return: A ToolboxToolCreator whose toolbox factory is mocked
        """
        toolbox_factory = MagicMock()
        if error is not None:
            toolbox_factory.create_tool_from_toolbox = MagicMock(side_effect=error)
        else:
            toolbox_factory.create_tool_from_toolbox = MagicMock(return_value=tool_from_toolbox)

        invocation_context = MagicMock()
        invocation_context.get_toolbox_factory = MagicMock(return_value=toolbox_factory)

        journal = MagicMock()
        journal.write_message = AsyncMock()

        return ToolboxToolCreator(MagicMock(), invocation_context, journal, self.AGENT_LOCATION, self.AGENT_SPEC)

    def test_list_check_requires_every_element_to_be_a_base_tool(self) -> None:
        """
        The pass-through applies to a list only when every element is a BaseTool.
        An empty list qualifies; a list with any other element, or a non-list, does not.
        """
        # The subTest label is a plain string: pytest-xdist has to serialize
        # subTest parameters to report them, and a MagicMock cannot be pickled.
        cases: List[Any] = [
            ("two base tools", [MagicMock(spec=BaseTool), MagicMock(spec=BaseTool)], True),
            ("empty list", [], True),
            ("base tool plus a dict", [MagicMock(spec=BaseTool), {"description": "not a tool"}], False),
            ("a dict, not a list", {"description": "a spec, not a list"}, False),
        ]
        for label, value, expected in cases:
            with self.subTest(case=label):
                # pylint: disable=protected-access
                self.assertIs(ToolboxToolCreator._is_list_of_base_tools(value), expected)

    async def test_base_tool_from_toolbox_is_returned_as_is(self) -> None:
        """
        A langchain BaseTool from the toolbox already carries its own schema and
        is returned unchanged. The spec's toolbox entry and args and the agent's
        name are what reach the toolbox.
        """
        predefined: MagicMock = MagicMock(spec=BaseTool)
        creator: ToolboxToolCreator = self.make_creator(tool_from_toolbox=predefined)

        result: Union[BaseTool, List[BaseTool]] = await creator.create_tool("searcher")

        self.assertIs(result, predefined)
        toolbox_factory = creator.invocation_context.get_toolbox_factory()
        toolbox_factory.create_tool_from_toolbox.assert_called_once_with("web_search", {"depth": 2}, "searcher")
        creator.journal.write_message.assert_not_awaited()

    async def test_list_of_base_tools_is_returned_as_is(self) -> None:
        """
        A toolbox entry may expand to several BaseTools; the list is returned unchanged.
        """
        predefined: List[MagicMock] = [MagicMock(spec=BaseTool), MagicMock(spec=BaseTool)]
        creator: ToolboxToolCreator = self.make_creator(tool_from_toolbox=predefined)

        result: Union[BaseTool, List[BaseTool]] = await creator.create_tool("searcher")

        self.assertIs(result, predefined)

    async def test_shared_coded_tool_spec_becomes_a_function_tool(self) -> None:
        """
        A toolbox entry that is a function specification (a shared coded tool)
        becomes a function tool named after the agent.
        """
        function_json: Dict[str, Any] = {
            "description": "Searches the web.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for."}
                },
                "required": ["query"]
            }
        }
        creator: ToolboxToolCreator = self.make_creator(tool_from_toolbox=function_json)

        result: Union[BaseTool, List[BaseTool]] = await creator.create_tool("searcher")

        self.assertIsInstance(result, BaseTool)
        self.assertEqual(result.name, "searcher")
        # The toolbox's spec is shared; the name must not have been written into it.
        self.assertNotIn("name", function_json)

    async def test_invalid_spec_is_reported_and_dropped(self) -> None:
        """
        A toolbox spec that cannot be turned into a tool is reported to the client
        journal as an invalid function spec, and the agent gets no tool for it.
        """
        creator: ToolboxToolCreator = self.make_creator(error=ToolSpecError("properties must be a dictionary"))

        result: Union[BaseTool, List[BaseTool]] = await creator.create_tool("searcher")

        self.assertIsNone(result)
        creator.journal.write_message.assert_awaited_once()
        reported: AgentMessage = creator.journal.write_message.await_args.args[0]
        self.assertIn("invalid function spec", reported.content)
        self.assertIn("searcher", reported.content)

    async def test_creation_error_is_reported_and_dropped(self) -> None:
        """
        Any other failure while the toolbox builds the tool is reported as a
        failed creation, and the agent gets no tool for it.
        """
        creator: ToolboxToolCreator = self.make_creator(error=ValueError("no such toolbox entry"))

        result: Union[BaseTool, List[BaseTool]] = await creator.create_tool("searcher")

        self.assertIsNone(result)
        creator.journal.write_message.assert_awaited_once()
        reported: AgentMessage = creator.journal.write_message.await_args.args[0]
        self.assertIn("Failed to create", reported.content)
        self.assertIn("no such toolbox entry", reported.content)
