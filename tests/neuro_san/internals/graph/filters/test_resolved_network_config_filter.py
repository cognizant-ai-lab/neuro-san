
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

from neuro_san.internals.graph.filters.network_config_filter_chain import NetworkConfigFilterChain
from neuro_san.internals.graph.filters.resolved_network_config_filter import ResolvedNetworkConfigFilter


class TestResolvedNetworkConfigFilter(TestCase):
    """
    Unit tests for ResolvedNetworkConfigFilter.

    The filter applies the standard NetworkConfigFilterChain to an agent network
    spec and strips the consumed "commondefs" block, always returning a copy.
    These tests pin the three properties its callers rely on: top-level defaults
    reach the agents, the input is never modified, and the output is a fixed
    point so the same filter can run again on the read side.
    """

    @staticmethod
    def _make_spec(front_man_schema: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Build a two-agent spec with the top-level defaults a deployment's llm_config.hocon
        typically defines: llm_config, max_execution_seconds and a "global" sly_data_schema
        that requires clients to send BYOK keys.

        :param front_man_schema: Optional sly_data_schema to put on the front man's function,
                so the merge with the global schema can be exercised.
        :return: The spec dictionary.
        """
        front_man_function: Dict[str, Any] = {"description": "Front man"}
        if front_man_schema is not None:
            front_man_function["sly_data_schema"] = front_man_schema
        return {
            "name": "network",
            "llm_config": {"model_name": "test-model"},
            "max_execution_seconds": 600,
            "sly_data_schema": {
                "type": "object",
                "properties": {
                    "llm_config": {
                        "type": "object",
                        "properties": {"openai_api_key": {"type": "string"}},
                    },
                },
                "required": ["llm_config"],
            },
            "tools": [
                {
                    "name": "front_man",
                    "function": front_man_function,
                    "instructions": "Delegate.",
                    "tools": ["helper"],
                },
                {
                    "name": "helper",
                    "function": {"description": "Helper"},
                    "instructions": "Help.",
                },
            ],
        }

    def test_filter_config_merges_global_defaults_into_agents(self) -> None:
        """
        The top-level defaults land on the agents: llm_config and max_execution_seconds on
        every agent, the sly_data_schema only on the front man's function.
        """
        resolved: Dict[str, Any] = ResolvedNetworkConfigFilter().filter_config(self._make_spec())

        front_man: Dict[str, Any] = resolved["tools"][0]
        helper: Dict[str, Any] = resolved["tools"][1]
        self.assertEqual("test-model", front_man["llm_config"]["model_name"])
        self.assertEqual("test-model", helper["llm_config"]["model_name"])
        self.assertEqual(600, front_man["max_execution_seconds"])
        self.assertEqual(600, helper["max_execution_seconds"])
        sly_data_schema: Dict[str, Any] = front_man["function"]["sly_data_schema"]
        self.assertEqual(["llm_config"], sly_data_schema["required"])
        self.assertIn("openai_api_key", sly_data_schema["properties"]["llm_config"]["properties"])
        self.assertNotIn("sly_data_schema", helper["function"])

    def test_filter_config_unions_front_man_required_with_global(self) -> None:
        """
        A front man that already declares its own sly_data_schema keeps it and gets the
        global one merged in, with the "required" lists unioned rather than replaced.
        """
        front_man_schema: Dict[str, Any] = {
            "type": "object",
            "properties": {"http_headers": {"type": "object"}},
            "required": ["http_headers"],
        }
        resolved: Dict[str, Any] = ResolvedNetworkConfigFilter().filter_config(
            self._make_spec(front_man_schema=front_man_schema))

        sly_data_schema: Dict[str, Any] = resolved["tools"][0]["function"]["sly_data_schema"]
        self.assertCountEqual(["llm_config", "http_headers"], sly_data_schema["required"])
        self.assertIn("http_headers", sly_data_schema["properties"])
        self.assertIn("llm_config", sly_data_schema["properties"])

    def test_filter_config_substitutes_and_strips_commondefs(self) -> None:
        """
        commondefs substitution is applied and the consumed block is removed from the result.
        """
        spec: Dict[str, Any] = self._make_spec()
        spec["commondefs"] = {"replacement_strings": {"greet": "hello"}}
        spec["tools"][0]["instructions"] = "{greet} world"

        resolved: Dict[str, Any] = ResolvedNetworkConfigFilter().filter_config(spec)

        self.assertEqual("hello world", resolved["tools"][0]["instructions"])
        self.assertNotIn("commondefs", resolved)

    def test_filter_config_does_not_mutate_input(self) -> None:
        """
        The input must come out untouched even though every filter that writes into a spec
        is exercised: defaults, commondefs substitution and stripping, and the in-place name
        correction of a "/" agent name.  Callers keep using the spec they deployed.
        """
        spec: Dict[str, Any] = self._make_spec()
        spec["commondefs"] = {"replacement_strings": {"greet": "hello"}}
        spec["tools"][0]["tools"] = ["help/er"]
        spec["tools"][1]["name"] = "help/er"
        expected: Dict[str, Any] = deepcopy(spec)

        resolved: Dict[str, Any] = ResolvedNetworkConfigFilter().filter_config(spec)

        # The whole dictionary, not just the keys the filters are known to touch.
        self.assertEqual(expected, spec)
        # ... while the result did get the correction on both ends of the edge.
        self.assertEqual("help_er", resolved["tools"][1]["name"])
        self.assertEqual(["help_er"], resolved["tools"][0]["tools"])

    def test_filter_config_returns_a_copy_without_tools(self) -> None:
        """
        The chain hands back the caller's own dict when there are no tools to work on;
        the filter must still return a copy so nothing downstream can reach the input.
        """
        spec_filter: ResolvedNetworkConfigFilter = ResolvedNetworkConfigFilter()
        for spec in ({"name": "empty", "tools": []}, {"name": "no_tools_key"}):
            with self.subTest(spec=spec):
                resolved: Dict[str, Any] = spec_filter.filter_config(spec)
                self.assertEqual(spec, resolved)
                self.assertIsNot(spec, resolved)

    def test_filter_config_output_is_a_fixed_point(self) -> None:
        """
        Filtering an already filtered spec changes nothing, so running the filter on both
        the write side and the read side is safe.

        The commondefs filters resolve one level of substitution per pass and never remove
        the "commondefs" block, so a spec that kept it would keep changing on every pass.
        The result must equal what a single hocon-style pass of the chain produces, minus
        that block, and a second pass must reproduce it exactly without touching its input.
        """
        spec: Dict[str, Any] = self._make_spec()
        spec["commondefs"] = {
            # Chained value substitution: a single pass resolves only one hop.
            "replacement_values": {"a": "b", "b": {"z": 1}},
            # Order-dependent string substitution: "punct" is visited before "who" needs it.
            "replacement_strings": {"punct": "!", "who": "world {punct}", "greet": "hello {who}"},
        }
        spec["tools"][0]["args"] = {"x": "a"}
        spec["tools"][0]["instructions"] = "{greet}"
        expected: Dict[str, Any] = NetworkConfigFilterChain().filter_config(spec)
        del expected["commondefs"]

        spec_filter: ResolvedNetworkConfigFilter = ResolvedNetworkConfigFilter()
        once: Dict[str, Any] = spec_filter.filter_config(spec)
        snapshot: Dict[str, Any] = deepcopy(once)
        twice: Dict[str, Any] = spec_filter.filter_config(once)

        self.assertNotIn("commondefs", once)
        self.assertEqual(expected, once)
        self.assertEqual(snapshot, twice)
        # The second pass did not mutate its input either.
        self.assertEqual(snapshot, once)

    def test_filter_config_none_returns_none(self) -> None:
        """
        A missing spec is passed through as None rather than raising.
        """
        self.assertIsNone(ResolvedNetworkConfigFilter().filter_config(None))
