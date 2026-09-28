
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

from unittest import TestCase
from unittest.mock import MagicMock

from langchain_core.tools import BaseTool

from neuro_san.internals.run_context.langchain.tools.function_tool_creator import FunctionToolCreator


class TestFunctionToolCreator(TestCase):
    """
    Unit tests for FunctionToolCreator.
    """

    AGENT_LOCATION: str = "agent 'researcher' of agent network 'deep/math_guy'"

    @staticmethod
    def make_creator() -> FunctionToolCreator:
        """
        Builds a creator with mocked collaborators.

        :return: A FunctionToolCreator with mocked collaborators
        """
        return FunctionToolCreator(MagicMock(), MagicMock(), MagicMock(), TestFunctionToolCreator.AGENT_LOCATION)

    def test_create_does_not_mutate_function_json(self) -> None:
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
        creator: FunctionToolCreator = self.make_creator()

        tool: BaseTool = creator.create(function_json, "music_guy")

        self.assertEqual(function_json, expected)
        self.assertEqual(tool.name, "music_guy")

    def test_none_function_json_raises_value_error(self) -> None:
        """
        An external agent that responded without a function has no spec.
        That is a ValueError naming the agent, so the external agent creator
        reports it as an invalid function definition.
        """
        creator: FunctionToolCreator = self.make_creator()

        with self.assertRaises(ValueError) as context:
            creator.create(None, "/network_b")

        self.assertIn("/network_b", str(context.exception))
