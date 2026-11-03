
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

    def test_tool_function_json_is_the_given_specification(self) -> None:
        """
        The tool is made from the function specification the creator was built with.
        """
        function_json: Dict[str, Any] = {
            "description": "Answers questions.",
        }
        creator: FunctionToolCreator = self.make_creator(function_json)

        self.assertIs(creator.get_tool_function_json(), function_json)

    def test_declares_no_parameters(self) -> None:
        """
        A function with no parameters, null ones, an empty dictionary or only an empty
        properties declaration declares no parameters, so the answer is True. One with
        properties or with a block in an unsupported dialect declares some, and a block or
        a properties value that is not a dictionary is malformed, so for those the answer
        is False. So it is for a function that is not a dictionary.
        """
        # Each case maps the "parameters" value of a function to the expected answer.
        cases: Dict[str, Dict[str, Any]] = {
            "null": {
                "parameters": None,
                "expected": True,
            },
            "empty_dictionary": {
                "parameters": {},
                "expected": True,
            },
            "empty_properties": {
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                "expected": True,
            },
            "with_properties": {
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                        },
                    },
                },
                "expected": False,
            },
            "not_a_dictionary": {
                "parameters": "question",
                "expected": False,
            },
            "properties_not_a_dictionary": {
                "parameters": {
                    "type": "object",
                    "properties": [],
                },
                "expected": False,
            },
            "unsupported_dialect": {
                "parameters": {
                    "type": "object",
                    "anyOf": [],
                },
                "expected": False,
            },
        }

        self.assertTrue(FunctionToolCreator.declares_no_parameters({"description": "Answers questions."}))
        self.assertFalse(FunctionToolCreator.declares_no_parameters("aaosa_call"))

        # Each label is a string, so the subTest parameters stay picklable under pytest-xdist.
        label: str = None
        for label in cases:
            with self.subTest(case=label):
                case: Dict[str, Any] = cases.get(label)
                function_json: Dict[str, Any] = {
                    "description": "Answers questions.",
                    "parameters": case.get("parameters"),
                }

                self.assertEqual(FunctionToolCreator.declares_no_parameters(function_json), case.get("expected"))
