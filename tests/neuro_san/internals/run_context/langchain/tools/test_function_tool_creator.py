
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

from copy import deepcopy

from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock

from langchain_core.tools import BaseTool

from neuro_san.internals.run_context.langchain.tools.function_tool_creator import FunctionToolCreator


class TestFunctionToolCreator(IsolatedAsyncioTestCase):
    """
    Unit tests for FunctionToolCreator.
    """

    AGENT_LOCATION: str = "agent 'researcher' of agent network 'deep/math_guy'"

    @staticmethod
    def make_creator(function_json: Dict[str, Any]) -> FunctionToolCreator:
        """
        Builds a creator for a function specification, with mocked collaborators.

        :param function_json: The function specification the creator is built for
        :return: A FunctionToolCreator with mocked collaborators
        """
        return FunctionToolCreator(MagicMock(), MagicMock(), MagicMock(), TestFunctionToolCreator.AGENT_LOCATION,
                                   function_json)

    async def test_create_tool_does_not_mutate_function_json(self) -> None:
        """
        Creating a tool must not add its lookup name to the caller-owned
        function specification, which can be a registry's live spec.
        """
        function_json: Dict[str, Any] = {
            "description": "Answers music questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to answer."
                    }
                },
                "required": ["question"]
            }
        }
        expected: Dict[str, Any] = deepcopy(function_json)
        creator: FunctionToolCreator = self.make_creator(function_json)

        tool: BaseTool = await creator.create_tool("music_guy")

        self.assertEqual(function_json, expected)
        self.assertEqual(tool.name, "music_guy")

    async def test_none_function_json_raises_value_error(self) -> None:
        """
        An external agent that responded without a function has no spec.
        That is a ValueError naming the agent, so the external agent creator
        reports it as an invalid function definition.
        """
        creator: FunctionToolCreator = self.make_creator(None)

        with self.assertRaises(ValueError) as context:
            await creator.create_tool("/network_b")

        self.assertIn("/network_b", str(context.exception))
