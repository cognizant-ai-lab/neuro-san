
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

from neuro_san.internals.graph.filters.name_correction_config_filter import NameCorrectionConfigFilter


class TestNameCorrectionConfigFilter(TestCase):
    """
    Unit tests for NameCorrectionConfigFilter.

    The filter corrects agent names that contain "/" (reserved for the agent
    hierarchy URI) by replacing it with "_", and rewrites every tools-list
    reference to a corrected agent so both ends of each edge agree.
    """

    @staticmethod
    def _make_spec(front_man_tools: List[Any], helper_name: str) -> Dict[str, Any]:
        """
        Build a two-agent network spec.

        :param front_man_tools: The front man's tools list, referencing the helper by name
        :param helper_name: The helper agent's declared name
        :return: The agent network spec dictionary
        """
        return {
            "tools": [
                {"name": "front", "function": {"description": "front"}, "tools": front_man_tools},
                {"name": helper_name, "function": {"description": "helper"}, "instructions": "Help."},
            ]
        }

    def test_corrects_slash_in_name_and_in_references(self) -> None:
        """
        A helper named "help/er" is renamed to "help_er" in its own "name" field, and the
        front man's reference to it is rewritten to match, with no stray key left behind.
        """
        spec: Dict[str, Any] = self._make_spec(["help/er"], "help/er")

        filtered: Dict[str, Any] = NameCorrectionConfigFilter().filter_config(spec)

        helper: Dict[str, Any] = filtered["tools"][1]
        self.assertEqual("help_er", helper["name"])
        self.assertNotIn("help/er", helper)
        self.assertEqual(["help_er"], filtered["tools"][0]["tools"])

    def test_valid_names_are_left_untouched(self) -> None:
        """
        A spec whose names are already valid comes back value-equal to the input.
        """
        spec: Dict[str, Any] = self._make_spec(["helper"], "helper")
        expected: Dict[str, Any] = deepcopy(spec)

        filtered: Dict[str, Any] = NameCorrectionConfigFilter().filter_config(spec)

        self.assertEqual(expected, filtered)

    def test_non_string_references_are_left_alone(self) -> None:
        """
        Dictionary entries in a tools list (e.g. MCP server definitions) are not names and
        must pass through unchanged while string references are still corrected.
        """
        mcp_tool: Dict[str, Any] = {"url": "https://mcp.example.com/mcp"}
        spec: Dict[str, Any] = self._make_spec(["help/er", mcp_tool], "help/er")

        filtered: Dict[str, Any] = NameCorrectionConfigFilter().filter_config(spec)

        self.assertEqual(["help_er", mcp_tool], filtered["tools"][0]["tools"])

    def test_uncorrectable_name_is_logged_and_left_as_is(self) -> None:
        """
        A tool without a name cannot be corrected: the filter logs an error and leaves the
        spec unchanged rather than raising.
        """
        spec: Dict[str, Any] = self._make_spec([], "helper")
        del spec["tools"][1]["name"]
        expected: Dict[str, Any] = deepcopy(spec)

        with self.assertLogs("NameCorrectionConfigFilter", level="ERROR") as captured:
            filtered: Dict[str, Any] = NameCorrectionConfigFilter().filter_config(spec)

        self.assertEqual(expected, filtered)
        self.assertEqual(1, len(captured.records))
        self.assertIn("no name for agent/tool", captured.records[0].getMessage())
