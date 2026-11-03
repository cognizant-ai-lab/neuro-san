
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

from unittest import TestCase

from neuro_san.internals.graph.filters.network_config_filter_chain import NetworkConfigFilterChain


class TestNetworkConfigFilterChain(TestCase):
    """
    Unit tests for NetworkConfigFilterChain: the filters it applies and their order.
    """

    def test_description_gets_its_replacement_strings(self) -> None:
        """
        A sub-agent's description that uses replacement strings is filled in inside
        the function block made from it.
        """
        config: Dict[str, Any] = {
            "commondefs": {
                "replacement_strings": {
                    "genre": "fiction",
                },
            },
            "tools": [
                {
                    "name": "book_recommender",
                    "instructions": "Recommend books.",
                    "tools": ["fiction_recommender"],
                },
                {
                    "name": "fiction_recommender",
                    "description": "Recommends {genre} books.",
                    "instructions": "Recommend {genre} books.",
                },
            ],
        }

        result: Dict[str, Any] = NetworkConfigFilterChain().filter_config(config)

        tools: List[Dict[str, Any]] = result.get("tools")
        expected: Dict[str, Any] = {
            "description": "Recommends fiction books.",
        }
        self.assertEqual(tools[1].get("function"), expected)
        self.assertIsNone(tools[0].get("function"))

    def test_agent_spec_from_replacement_values_gets_a_function(self) -> None:
        """
        A sub-agent spec that comes whole from replacement_values gets its function
        block, because DescriptionConfigFilter runs after commondefs substitution.
        """
        config: Dict[str, Any] = {
            "commondefs": {
                "replacement_values": {
                    "fiction_spec": {
                        "name": "fiction_recommender",
                        "description": "Recommends fiction books.",
                        "instructions": "Recommend fiction books.",
                    },
                },
            },
            "tools": [
                {
                    "name": "book_recommender",
                    "instructions": "Recommend books.",
                    "tools": ["fiction_recommender"],
                },
                "fiction_spec",
            ],
        }

        result: Dict[str, Any] = NetworkConfigFilterChain().filter_config(config)

        expected: Dict[str, Any] = {
            "description": "Recommends fiction books.",
        }
        self.assertEqual(result.get("tools")[1].get("function"), expected)

    def test_front_man_description_joins_the_global_sly_data_schema(self) -> None:
        """
        A front man that gives only a top-level description keeps the sly_data_schema
        that the network-wide defaults put into its function block, and gets the description too.
        """
        config: Dict[str, Any] = {
            "sly_data_schema": {
                "type": "object",
                "properties": {
                    "llm_config": {
                        "type": "object",
                    },
                },
                "required": ["llm_config"],
            },
            "tools": [
                {
                    "name": "book_recommender",
                    "description": "Recommends books.",
                    "instructions": "Recommend books.",
                },
            ],
        }

        result: Dict[str, Any] = NetworkConfigFilterChain().filter_config(config)

        function: Dict[str, Any] = result.get("tools")[0].get("function")
        self.assertEqual(function.get("description"), "Recommends books.")
        self.assertEqual(function.get("sly_data_schema").get("required"), ["llm_config"])
        self.assertIsNone(function.get("parameters"))

    def test_function_without_parameters_is_left_as_written(self) -> None:
        """
        A sub-agent whose function block declares no parameters keeps it as written.
        Only the tool its caller uses gets a default, so a coded tool that calls the
        sub-agent can still pass any arguments.
        """
        config: Dict[str, Any] = {
            "tools": [
                {
                    "name": "book_recommender",
                    "instructions": "Recommend books.",
                    "tools": ["fiction_recommender"],
                },
                {
                    "name": "fiction_recommender",
                    "function": {
                        "description": "Recommends fiction books.",
                    },
                    "instructions": "Recommend fiction books.",
                },
            ],
        }

        result: Dict[str, Any] = NetworkConfigFilterChain().filter_config(config)

        self.assertEqual(result, config)

    def test_coded_tool_with_description_gets_a_function_without_parameters(self) -> None:
        """
        A coded tool that gives only a top-level description gets a function block with
        that description and no parameters, so it is still called without arguments.
        """
        config: Dict[str, Any] = {
            "tools": [
                {
                    "name": "announcer",
                    "instructions": "Tell the user the time.",
                    "tools": ["clock"],
                },
                {
                    "name": "clock",
                    "description": "Returns the current time.",
                    "class": "clock.Clock",
                },
            ],
        }

        result: Dict[str, Any] = NetworkConfigFilterChain().filter_config(config)

        expected: Dict[str, Any] = {
            "description": "Returns the current time.",
        }
        self.assertEqual(result.get("tools")[1].get("function"), expected)
