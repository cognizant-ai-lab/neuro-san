
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

from neuro_san.internals.graph.filters.default_parameters_config_filter import DefaultParametersConfigFilter


class TestDefaultParametersConfigFilter(TestCase):
    """
    Unit tests for DefaultParametersConfigFilter: which agents get the default
    parameters, and that every other network comes back untouched.
    """

    LOGGER_NAME: str = "DefaultParametersConfigFilter"

    FRONT_MAN: Dict[str, Any] = {
        "name": "book_recommender",
        "instructions": "Recommend books.",
        "function": {
            "description": "Recommends books.",
        },
        "tools": ["fiction_recommender"],
    }

    EXPECTED_PARAMETERS: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "inquiry": {
                "type": "string",
                "description": "The request to send to this agent.",
            },
        },
        "required": ["inquiry"],
    }

    @staticmethod
    def make_helper() -> Dict[str, Any]:
        """
        Makes an LLM sub-agent spec whose function block has a description and no parameters.

        :return: A new sub-agent spec dictionary
        """
        helper: Dict[str, Any] = {
            "name": "fiction_recommender",
            "function": {
                "description": "Recommends fiction books.",
            },
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

        result: Dict[str, Any] = DefaultParametersConfigFilter().filter_config(config)

        self.assertIs(result, config)
        self.assertEqual(result, before)

    def test_sub_agent_without_parameters_gets_the_default(self) -> None:
        """
        An LLM sub-agent whose function block has no parameters gets a single
        required "inquiry" string parameter, and keeps its description.
        """
        config: Dict[str, Any] = self.make_config([self.make_helper()])

        result: Dict[str, Any] = DefaultParametersConfigFilter().filter_config(config)

        tools: List[Dict[str, Any]] = result.get("tools")
        expected: Dict[str, Any] = {
            "description": "Recommends fiction books.",
            "parameters": self.EXPECTED_PARAMETERS,
        }
        self.assertEqual(tools[1].get("function"), expected)
        self.assertEqual(tools[0], self.FRONT_MAN)

    def test_input_is_not_modified(self) -> None:
        """
        The parameters are added to a copy, never to the caller's dictionary.
        """
        config: Dict[str, Any] = self.make_config([self.make_helper()])
        before: Dict[str, Any] = deepcopy(config)

        result: Dict[str, Any] = DefaultParametersConfigFilter().filter_config(config)

        self.assertIsNot(result, config)
        self.assertEqual(config, before)

    def test_null_parameters_count_as_missing(self) -> None:
        """
        Parameters that are explicitly null are treated like missing ones.
        """
        helper: Dict[str, Any] = self.make_helper()
        function: Dict[str, Any] = helper.get("function")
        function["parameters"] = None
        config: Dict[str, Any] = self.make_config([helper])

        result: Dict[str, Any] = DefaultParametersConfigFilter().filter_config(config)

        result_function: Dict[str, Any] = result.get("tools")[1].get("function")
        self.assertEqual(result_function.get("parameters"), self.EXPECTED_PARAMETERS)

    def test_declared_parameters_are_kept(self) -> None:
        """
        A sub-agent that declares its own parameters keeps them as written.
        """
        helper: Dict[str, Any] = self.make_helper()
        function: Dict[str, Any] = helper.get("function")
        function["parameters"] = {
            "type": "object",
            "properties": {
                "genre": {
                    "type": "string",
                    "description": "The genre to recommend.",
                },
            },
        }

        self.assert_unchanged(self.make_config([helper]))

    def test_empty_parameters_are_kept(self) -> None:
        """
        An empty parameters dictionary is neither missing nor null, so it is kept as written.
        """
        helper: Dict[str, Any] = self.make_helper()
        function: Dict[str, Any] = helper.get("function")
        function["parameters"] = {}

        self.assert_unchanged(self.make_config([helper]))

    def test_top_level_parameters_are_left_for_the_validators(self) -> None:
        """
        A sub-agent that gives its parameters outside its function block gets no default,
        so the validators still check those parameters, and a warning names the agent.
        """
        helper: Dict[str, Any] = self.make_helper()
        helper["parameters"] = {
            "type": "object",
            "properties": {
                "genre": {
                    "type": "string",
                    "description": "The genre to recommend.",
                },
            },
        }

        with self.assertLogs(self.LOGGER_NAME, level="WARNING") as logs:
            self.assert_unchanged(self.make_config([helper]))

        self.assertIn("fiction_recommender", logs.output[0])
        self.assertIn("parameters only work inside the function block", logs.output[0])

    def test_a_shared_function_block_changes_only_for_the_sub_agent(self) -> None:
        """
        When agents share one function dictionary, only the sub-agent's function block
        gets the parameters. The front man and the coded tool keep the shared one as it is.
        """
        shared_function: Dict[str, Any] = {
            "description": "Shared description.",
        }
        front_man: Dict[str, Any] = {
            "name": "book_recommender",
            "function": shared_function,
            "tools": ["fiction_recommender", "book_finder"],
        }
        helper: Dict[str, Any] = {
            "name": "fiction_recommender",
            "function": shared_function,
            "instructions": "Recommend fiction books.",
        }
        coded_tool: Dict[str, Any] = {
            "name": "book_finder",
            "function": shared_function,
            "class": "books.BookFinder",
        }
        config: Dict[str, Any] = {
            "tools": [front_man, helper, coded_tool],
        }

        result: Dict[str, Any] = DefaultParametersConfigFilter().filter_config(config)

        tools: List[Dict[str, Any]] = result.get("tools")
        self.assertIsNone(tools[0].get("function").get("parameters"))
        self.assertEqual(tools[1].get("function").get("parameters"), self.EXPECTED_PARAMETERS)
        self.assertIsNone(tools[2].get("function").get("parameters"))
        self.assertIsNone(shared_function.get("parameters"))

    def test_front_man_gets_no_parameters(self) -> None:
        """
        The front man, the first tool in the list, gets its input from the chat, so it
        gets no parameters even though its function block has none.
        """
        config: Dict[str, Any] = {
            "tools": [deepcopy(self.FRONT_MAN)],
        }

        self.assert_unchanged(config)

    def test_agents_that_are_not_llm_agents_are_left_alone(self) -> None:
        """
        A coded tool and a toolbox agent do not run as LLM agents, so they get no parameters.
        """
        # Each case adds one key to the helper spec.
        extra_keys: Dict[str, Dict[str, Any]] = {
            "coded_tool": {
                "key": "class",
                "value": "fiction.Recommender",
            },
            "toolbox": {
                "key": "toolbox",
                "value": "website_search",
            },
        }

        # Each label is a string, so the subTest parameters stay picklable under pytest-xdist.
        label: str = None
        for label in extra_keys:
            with self.subTest(case=label):
                extra: Dict[str, Any] = extra_keys.get(label)
                helper: Dict[str, Any] = self.make_helper()
                helper[extra.get("key")] = extra.get("value")

                self.assert_unchanged(self.make_config([helper]))

    def test_agents_without_a_function_block_are_left_alone(self) -> None:
        """
        An agent without a function block cannot be called, and a function value that
        is not a dictionary is reported by the validators, so neither gets parameters.
        """
        helpers: Dict[str, Dict[str, Any]] = {
            "missing": {
                "name": "fiction_recommender",
                "instructions": "Recommend fiction books.",
            },
            "null": {
                "name": "fiction_recommender",
                "function": None,
                "instructions": "Recommend fiction books.",
            },
            "unresolved_reference": {
                "name": "fiction_recommender",
                "function": "aaosa_call",
                "instructions": "Recommend fiction books.",
            },
        }

        # Each label is a string, so the subTest parameters stay picklable under pytest-xdist.
        label: str = None
        for label in helpers:
            with self.subTest(case=label):
                self.assert_unchanged(self.make_config([deepcopy(helpers.get(label))]))

    def test_non_dictionary_entries_are_skipped(self) -> None:
        """
        A tools entry that is not a dictionary is skipped, and later agents still get
        their parameters.
        """
        config: Dict[str, Any] = self.make_config(["not_an_agent", self.make_helper()])

        result: Dict[str, Any] = DefaultParametersConfigFilter().filter_config(config)

        tools: List[Any] = result.get("tools")
        self.assertEqual(tools[1], "not_an_agent")
        self.assertEqual(tools[2].get("function").get("parameters"), self.EXPECTED_PARAMETERS)

    def test_each_agent_gets_its_own_parameters(self) -> None:
        """
        No two agents share a parameters dictionary, and none shares the class default.
        """
        second_helper: Dict[str, Any] = self.make_helper()
        second_helper["name"] = "study_book_recommender"
        config: Dict[str, Any] = self.make_config([self.make_helper(), second_helper])

        result: Dict[str, Any] = DefaultParametersConfigFilter().filter_config(config)

        tools: List[Dict[str, Any]] = result.get("tools")
        first_parameters: Dict[str, Any] = tools[1].get("function").get("parameters")
        second_parameters: Dict[str, Any] = tools[2].get("function").get("parameters")
        self.assertIsNot(first_parameters, second_parameters)
        self.assertIsNot(first_parameters, DefaultParametersConfigFilter.DEFAULT_PARAMETERS)

        first_parameters.get("required").append("extra")
        self.assertEqual(second_parameters.get("required"), ["inquiry"])
        self.assertEqual(DefaultParametersConfigFilter.DEFAULT_PARAMETERS.get("required"), ["inquiry"])

    def test_output_is_a_fixed_point(self) -> None:
        """
        Filtering a filtered config again changes nothing, as the reservation readers rely on.
        """
        config: Dict[str, Any] = self.make_config([self.make_helper()])
        my_filter: DefaultParametersConfigFilter = DefaultParametersConfigFilter()

        once: Dict[str, Any] = my_filter.filter_config(config)
        twice: Dict[str, Any] = my_filter.filter_config(once)

        self.assertIs(twice, once)

    def test_configs_without_tools_are_returned_as_is(self) -> None:
        """
        None, a config with no tools, an empty tools list and a tools value that is
        not a list all come back unchanged.
        """
        self.assertIsNone(DefaultParametersConfigFilter().filter_config(None))

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
