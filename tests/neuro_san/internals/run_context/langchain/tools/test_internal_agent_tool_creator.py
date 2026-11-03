
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

from neuro_san.internals.run_context.langchain.tools.internal_agent_tool_creator import InternalAgentToolCreator


class TestInternalAgentToolCreator(IsolatedAsyncioTestCase):
    """
    Unit tests for InternalAgentToolCreator: when the tool for an LLM agent of the
    network gets the default "inquiry" parameter, and that the agent's spec keeps
    what its author wrote.
    """

    AGENT_LOCATION: str = "agent 'researcher' of agent network 'deep/math_guy'"

    @staticmethod
    def make_creator(function_json: Dict[str, Any]) -> InternalAgentToolCreator:
        """
        Builds a creator for a function specification, with mocked collaborators.

        :param function_json: The function specification the creator is built for
        :return: An InternalAgentToolCreator with mocked collaborators
        """
        return InternalAgentToolCreator(MagicMock(), MagicMock(), MagicMock(),
                                        TestInternalAgentToolCreator.AGENT_LOCATION, function_json)

    async def test_function_without_parameters_gets_the_default(self) -> None:
        """
        The tool for an agent whose function declares no parameters has a single
        required "inquiry" string argument.
        """
        function_json: Dict[str, Any] = {
            "description": "Answers questions.",
        }

        tool: BaseTool = await self.make_creator(function_json).create_tool("helper")

        schema: Dict[str, Any] = tool.get_input_jsonschema()
        self.assertEqual(list(schema.get("properties").keys()), ["inquiry"])
        self.assertEqual(schema.get("properties").get("inquiry").get("type"), "string")
        self.assertEqual(schema.get("required"), ["inquiry"])
        self.assertEqual(tool.name, "helper")
        self.assertEqual(tool.description, "Answers questions.")

    async def test_spec_keeps_no_parameters(self) -> None:
        """
        Only the tool gets the default. The function specification, which is part
        of the agent's spec in the registry, keeps no parameters.
        """
        function_json: Dict[str, Any] = {
            "description": "Answers questions.",
        }
        expected: Dict[str, Any] = deepcopy(function_json)

        await self.make_creator(function_json).create_tool("helper")

        self.assertEqual(function_json, expected)

    async def test_declared_parameters_are_kept(self) -> None:
        """
        The tool for an agent that declares its own parameters has exactly those parameters.
        """
        function_json: Dict[str, Any] = {
            "description": "Recommends books.",
            "parameters": {
                "type": "object",
                "properties": {
                    "genre": {
                        "type": "string",
                        "description": "The genre to recommend.",
                    },
                },
                "required": ["genre"],
            },
        }

        tool: BaseTool = await self.make_creator(function_json).create_tool("helper")

        schema: Dict[str, Any] = tool.get_input_jsonschema()
        self.assertEqual(list(schema.get("properties").keys()), ["genre"])
        self.assertEqual(schema.get("required"), ["genre"])

    async def test_empty_parameters_count_as_none(self) -> None:
        """
        Null parameters, an empty dictionary and an empty or null properties declaration
        all declare no parameters, so each of these tools gets the default.
        """
        parameters_cases: Dict[str, Any] = {
            "null": None,
            "empty_dictionary": {},
            "type_only": {
                "type": "object",
            },
            "empty_properties": {
                "type": "object",
                "properties": {},
            },
            "null_properties": {
                "type": "object",
                "properties": None,
            },
        }

        # Each label is a string, so the subTest parameters stay picklable under pytest-xdist.
        label: str = None
        for label in parameters_cases:
            with self.subTest(case=label):
                function_json: Dict[str, Any] = {
                    "description": "Answers questions.",
                    "parameters": parameters_cases.get(label),
                }

                tool: BaseTool = await self.make_creator(function_json).create_tool("helper")

                self.assertEqual(tool.get_input_jsonschema().get("required"), ["inquiry"])

    async def test_function_that_is_not_a_dictionary_raises_value_error(self) -> None:
        """
        A "function" that is not a dictionary, which only a spec that skipped validation
        can have, raises a ValueError, as it does for a coded tool. The chat session
        reports a ValueError to the client and ends the request.
        """
        function_cases: Dict[str, Any] = {
            "string": "aaosa_call",
            "list": [],
        }

        # Each label is a string, so the subTest parameters stay picklable under pytest-xdist.
        label: str = None
        for label in function_cases:
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    await self.make_creator(function_cases.get(label)).create_tool("helper")

    async def test_properties_that_are_not_a_dictionary_raise_value_error(self) -> None:
        """
        A properties value that is not a dictionary, such as [] or false, is malformed,
        so the tool does not get the default. Building it raises a ValueError that names
        the problem, which the validators do not catch.
        """
        properties_cases: Dict[str, Any] = {
            "list": [],
            "empty_string": "",
            "false": False,
        }

        # Each label is a string, so the subTest parameters stay picklable under pytest-xdist.
        label: str = None
        for label in properties_cases:
            with self.subTest(case=label):
                function_json: Dict[str, Any] = {
                    "description": "Answers questions.",
                    "parameters": {
                        "type": "object",
                        "properties": properties_cases.get(label),
                    },
                }

                with self.assertRaises(ValueError):
                    await self.make_creator(function_json).create_tool("helper")
