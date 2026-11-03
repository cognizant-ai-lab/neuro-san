
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

from copy import deepcopy
from unittest import TestCase

from neuro_san.internals.graph.filters.description_config_filter import DescriptionConfigFilter


class TestDescriptionConfigFilter(TestCase):
    """
    Unit tests for DescriptionConfigFilter: how a top-level description fills in a
    function block, which unused descriptions are reported, and that every other
    network comes back untouched.
    """

    LOGGER_NAME: str = "DescriptionConfigFilter"

    FRONT_MAN: Dict[str, Any] = {
        "name": "book_recommender",
        "instructions": "Recommend books.",
        "tools": ["fiction_recommender"],
    }

    EXPECTED_FUNCTION: Dict[str, Any] = {
        "description": "Recommends fiction books.",
    }

    @staticmethod
    def make_helper(description: Any = "Recommends fiction books.") -> Dict[str, Any]:
        """
        Makes a sub-agent spec that gives a description in place of a function block.

        :param description: The value of the "description" key
        :return: A new sub-agent spec dictionary
        """
        helper: Dict[str, Any] = {
            "name": "fiction_recommender",
            "description": description,
            "instructions": "Recommend fiction books.",
        }
        return helper

    def make_config(self, tools: List[Any]) -> Dict[str, Any]:
        """
        Makes an agent network config with the test front man followed by the given tools.

        :param tools: The tools to list after the front man
        :return: A new agent network config dictionary
        """
        all_tools: List[Any] = [deepcopy(self.FRONT_MAN)]
        all_tools.extend(tools)
        config: Dict[str, Any] = {
            "llm_config": {
                "model_name": "gpt-4o",
            },
            "tools": all_tools,
        }
        return config

    def assert_unchanged(self, config: Dict[str, Any]) -> None:
        """
        Asserts that filtering the config hands back the very same dictionary, unmodified.

        :param config: The agent network config to filter
        """
        before: Dict[str, Any] = deepcopy(config)

        result: Dict[str, Any] = DescriptionConfigFilter().filter_config(config)

        self.assertIs(result, config)
        self.assertEqual(result, before)

    def test_sub_agent_with_description_gets_a_function_block(self) -> None:
        """
        A sub-agent with a description and no function block gets one made from its description.
        """
        config: Dict[str, Any] = self.make_config([self.make_helper()])

        result: Dict[str, Any] = DescriptionConfigFilter().filter_config(config)

        tools: List[Dict[str, Any]] = result.get("tools")
        self.assertEqual(tools[1].get("function"), self.EXPECTED_FUNCTION)
        # Everything the author wrote stays as it was.
        self.assertEqual(tools[1].get("description"), "Recommends fiction books.")
        self.assertEqual(tools[1].get("instructions"), "Recommend fiction books.")
        self.assertEqual(tools[0], self.FRONT_MAN)

    def test_input_is_not_modified(self) -> None:
        """
        The function block is added to a copy, never to the caller's dictionary.
        """
        config: Dict[str, Any] = self.make_config([self.make_helper()])
        before: Dict[str, Any] = deepcopy(config)

        result: Dict[str, Any] = DescriptionConfigFilter().filter_config(config)

        self.assertIsNot(result, config)
        self.assertEqual(config, before)

    def test_null_function_counts_as_missing(self) -> None:
        """
        A function block that is explicitly null is treated like a missing one.
        """
        helper: Dict[str, Any] = self.make_helper()
        helper["function"] = None
        config: Dict[str, Any] = self.make_config([helper])

        result: Dict[str, Any] = DescriptionConfigFilter().filter_config(config)

        self.assertEqual(result.get("tools")[1].get("function"), self.EXPECTED_FUNCTION)

    def test_front_man_with_description_gets_a_function_block(self) -> None:
        """
        The front man's description goes into a function block too, so clients get it
        from the Function API.
        """
        front_man: Dict[str, Any] = deepcopy(self.FRONT_MAN)
        front_man["description"] = "Recommends books."
        config: Dict[str, Any] = {
            "tools": [front_man],
        }

        result: Dict[str, Any] = DescriptionConfigFilter().filter_config(config)

        expected: Dict[str, Any] = {
            "description": "Recommends books.",
        }
        self.assertEqual(result.get("tools")[0].get("function"), expected)

    def test_front_man_keeps_what_its_function_block_has(self) -> None:
        """
        A front man whose function block has no description, for example one holding only
        the sly_data_schema that DefaultsConfigFilter adds, gets the description added to it.
        """
        front_man: Dict[str, Any] = deepcopy(self.FRONT_MAN)
        front_man["description"] = "Recommends books."
        front_man["function"] = {
            "sly_data_schema": {
                "type": "object",
            },
        }
        config: Dict[str, Any] = {
            "tools": [front_man],
        }

        result: Dict[str, Any] = DescriptionConfigFilter().filter_config(config)

        expected: Dict[str, Any] = {
            "sly_data_schema": {
                "type": "object",
            },
            "description": "Recommends books.",
        }
        self.assertEqual(result.get("tools")[0].get("function"), expected)

    def test_function_block_without_description_gets_it(self) -> None:
        """
        A sub-agent whose function block has parameters but no description gets the
        description added, and its own parameters are kept as written.
        """
        parameters: Dict[str, Any] = {
            "type": "object",
            "properties": {
                "genre": {
                    "type": "string",
                    "description": "The genre to recommend.",
                },
            },
        }
        helper: Dict[str, Any] = self.make_helper()
        helper["function"] = {
            "parameters": deepcopy(parameters),
        }
        config: Dict[str, Any] = self.make_config([helper])

        result: Dict[str, Any] = DescriptionConfigFilter().filter_config(config)

        expected: Dict[str, Any] = {
            "parameters": parameters,
            "description": "Recommends fiction books.",
        }
        self.assertEqual(result.get("tools")[1].get("function"), expected)

    def test_function_description_wins_over_description(self) -> None:
        """
        An agent whose function block has its own description keeps it as written,
        without a warning. So does an agent whose function value is not a dictionary,
        which the validators report.
        """
        functions: Dict[str, Any] = {
            "written_by_hand": {
                "description": "Written by hand.",
            },
            "unresolved_reference": "aaosa_call",
        }

        # Each label is a string, so the subTest parameters stay picklable under pytest-xdist.
        label: str = None
        for label in functions:
            with self.subTest(case=label):
                helper: Dict[str, Any] = self.make_helper()
                helper["function"] = functions.get(label)

                with self.assertNoLogs(self.LOGGER_NAME, level="WARNING"):
                    self.assert_unchanged(self.make_config([helper]))

    def test_agents_that_cannot_use_a_description_are_reported(self) -> None:
        """
        A toolbox agent and an agent with top-level parameters get no function block
        made, and a warning says why.
        """
        # Each case adds one key to the helper spec, and the warning must give the matching reason.
        extra_keys: Dict[str, Dict[str, Any]] = {
            "toolbox": {
                "key": "toolbox",
                "value": "website_search",
                "reason": "toolbox",
            },
            "parameters": {
                "key": "parameters",
                "value": {
                    "type": "object",
                },
                "reason": "put them in function.parameters",
            },
        }

        # Each label is a string, so the subTest parameters stay picklable under pytest-xdist.
        label: str = None
        for label in extra_keys:
            with self.subTest(case=label):
                extra: Dict[str, Any] = extra_keys.get(label)
                helper: Dict[str, Any] = self.make_helper()
                helper[extra.get("key")] = extra.get("value")

                with self.assertLogs(self.LOGGER_NAME, level="WARNING") as logs:
                    self.assert_unchanged(self.make_config([helper]))

                self.assertIn("fiction_recommender", logs.output[0])
                self.assertIn(extra.get("reason"), logs.output[0])

    def test_agent_without_description_is_left_alone(self) -> None:
        """
        A sub-agent with neither a function block nor a description is left as it was, without a warning.
        """
        helper: Dict[str, Any] = self.make_helper()
        del helper["description"]

        with self.assertNoLogs(self.LOGGER_NAME, level="WARNING"):
            self.assert_unchanged(self.make_config([helper]))

    def test_bad_description_is_reported_and_left_alone(self) -> None:
        """
        A description that is blank or not a string makes no function block,
        and a warning names the agent and the problem.
        """
        # Each case maps a bad description to the words its warning must contain.
        bad_descriptions: Dict[str, Dict[str, Any]] = {
            "empty": {
                "value": "",
                "reason": "it is blank",
            },
            "blank": {
                "value": "   ",
                "reason": "it is blank",
            },
            "number": {
                "value": 42,
                "reason": "not int",
            },
            "list": {
                "value": ["Recommends fiction books."],
                "reason": "not list",
            },
        }

        # Each label is a string, so the subTest parameters stay picklable under pytest-xdist.
        label: str = None
        for label in bad_descriptions:
            with self.subTest(case=label):
                bad: Dict[str, Any] = bad_descriptions.get(label)
                config: Dict[str, Any] = self.make_config([self.make_helper(bad.get("value"))])

                with self.assertLogs(self.LOGGER_NAME, level="WARNING") as logs:
                    self.assert_unchanged(config)

                self.assertIn("fiction_recommender", logs.output[0])
                self.assertIn(bad.get("reason"), logs.output[0])

    def test_non_dictionary_entries_are_skipped(self) -> None:
        """
        A tools entry that is not a dictionary is skipped, and later agents still get
        their function block.
        """
        config: Dict[str, Any] = self.make_config(["not_an_agent", self.make_helper()])

        result: Dict[str, Any] = DescriptionConfigFilter().filter_config(config)

        tools: List[Any] = result.get("tools")
        self.assertEqual(tools[1], "not_an_agent")
        self.assertEqual(tools[2].get("function"), self.EXPECTED_FUNCTION)

    def test_output_is_a_fixed_point(self) -> None:
        """
        Filtering a filtered config again changes nothing, as the reservation readers rely on.
        """
        config: Dict[str, Any] = self.make_config([self.make_helper()])
        my_filter: DescriptionConfigFilter = DescriptionConfigFilter()

        once: Dict[str, Any] = my_filter.filter_config(config)
        twice: Dict[str, Any] = my_filter.filter_config(once)

        self.assertIs(twice, once)

    def test_configs_without_tools_are_returned_as_is(self) -> None:
        """
        None, a config with no tools, an empty tools list and a tools value that is
        not a list all come back unchanged.
        """
        self.assertIsNone(DescriptionConfigFilter().filter_config(None))

        configs: Dict[str, Dict[str, Any]] = {
            "no_tools": {
                "llm_config": {
                    "model_name": "gpt-4o",
                },
            },
            "empty_tools": {
                "tools": [],
            },
            "tools_is_a_string": {
                "tools": "fiction_recommender",
            },
            # A value with no length, so the list check is what keeps it from failing.
            "tools_is_a_number": {
                "tools": 42,
            },
        }

        # Each label is a string, so the subTest parameters stay picklable under pytest-xdist.
        label: str = None
        for label in configs:
            with self.subTest(case=label):
                self.assert_unchanged(configs.get(label))
