
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
from typing import Optional

from copy import deepcopy
from unittest import TestCase

from neuro_san.internals.graph.filters.name_correction_config_filter import NameCorrectionConfigFilter


class TestNameCorrectionConfigFilter(TestCase):
    """
    Unit tests for NameCorrectionConfigFilter.

    The filter corrects agent names that contain "/" (reserved for the agent
    hierarchy URI) by replacing it with "_", and rewrites every reference to a
    corrected agent, in tools lists and in args.tools, so both ends of each edge agree.
    """

    @staticmethod
    def _make_spec(front_man_tools: List[Any], helper_name: str,
                   front_man_args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Build a two-agent network spec.

        :param front_man_tools: The front man's tools list, referencing the helper by name
        :param helper_name: The helper agent's declared name
        :param front_man_args: Optional "args" dictionary for the front man. When None the
                front man carries no "args" key at all, so tests can prove that the filter
                never creates one.
        :return: The agent network spec dictionary
        """
        front_man: Dict[str, Any] = {"name": "front", "function": {"description": "front"}, "tools": front_man_tools}
        if front_man_args is not None:
            front_man["args"] = front_man_args
        return {
            "tools": [
                front_man,
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

    def test_corrects_list_form_args_tools_references(self) -> None:
        """
        A coded tool declaring its downstream agents as a list in args.tools has the
        string entry "help/er" rewritten to "help_er" alongside the helper's own rename.
        The front man's tools list is empty here so the rewrite is proven to run for
        tools that hold no tools-list references at all.
        """
        spec: Dict[str, Any] = self._make_spec([], "help/er", {"tools": ["help/er"]})

        filtered: Dict[str, Any] = NameCorrectionConfigFilter().filter_config(spec)

        self.assertEqual("help_er", filtered["tools"][1]["name"])
        self.assertEqual(["help_er"], filtered["tools"][0]["args"]["tools"])

    def test_corrects_dict_form_args_tools_values_and_keeps_keys(self) -> None:
        """
        A coded tool declaring its downstream agents as a dict in args.tools has the
        value "help/er" rewritten to "help_er" while the label key stays untouched, since
        the labels are the coded tool's own lookup keys.
        """
        spec: Dict[str, Any] = self._make_spec([], "help/er", {"tools": {"helper": "help/er"}})

        filtered: Dict[str, Any] = NameCorrectionConfigFilter().filter_config(spec)

        self.assertEqual({"helper": "help_er"}, filtered["tools"][0]["args"]["tools"])

    def test_non_string_args_tools_entries_and_tools_without_args_are_left_alone(self) -> None:
        """
        Non-string entries in args.tools (an int and a dict) pass through exactly as given
        while the string reference next to them is still corrected, and a tool that has no
        "args" at all gains nothing beyond its own name correction.
        """
        mcp_tool: Dict[str, Any] = {"url": "https://mcp.example.com/mcp"}
        spec: Dict[str, Any] = self._make_spec([], "help/er", {"tools": ["help/er", 42, mcp_tool]})
        expected_front_args: Dict[str, Any] = deepcopy(spec["tools"][0]["args"])
        expected_helper: Dict[str, Any] = deepcopy(spec["tools"][1])

        filtered: Dict[str, Any] = NameCorrectionConfigFilter().filter_config(spec)

        # Only the string reference changes; the int and the dict are value-equal to the copy.
        expected_front_args["tools"][0] = "help_er"
        self.assertEqual(expected_front_args, filtered["tools"][0]["args"])
        # The helper never had "args" and must not have acquired one.
        expected_helper["name"] = "help_er"
        self.assertEqual(expected_helper, filtered["tools"][1])
        self.assertNotIn("args", filtered["tools"][1])

    def test_corrects_name_referenced_from_both_tools_and_args_tools(self) -> None:
        """
        A corrected name that is referenced from both the tools list and args.tools of the
        same tool is rewritten in both places from the one corrections table.
        """
        spec: Dict[str, Any] = self._make_spec(["help/er"], "help/er", {"tools": {"helper": "help/er"}})

        filtered: Dict[str, Any] = NameCorrectionConfigFilter().filter_config(spec)

        self.assertEqual(["help_er"], filtered["tools"][0]["tools"])
        self.assertEqual({"helper": "help_er"}, filtered["tools"][0]["args"]["tools"])

    def test_args_without_tools_key_does_not_gain_one(self) -> None:
        """
        A tool whose args carries no "tools" key is left value-equal to the input: the
        filter never creates args.tools, because its absence means the tool declares no
        downstream agents.
        """
        spec: Dict[str, Any] = self._make_spec(["help/er"], "help/er", {"verbose": True})
        expected_args: Dict[str, Any] = deepcopy(spec["tools"][0]["args"])

        filtered: Dict[str, Any] = NameCorrectionConfigFilter().filter_config(spec)

        self.assertEqual(expected_args, filtered["tools"][0]["args"])
        self.assertNotIn("tools", filtered["tools"][0]["args"])

    def test_other_args_tools_shapes_are_left_alone(self) -> None:
        """
        An args.tools that is neither a list nor a dict (here a bare string) is malformed.
        The filter leaves it exactly as given because ToolsShapeValidator is the place that
        reports the shape error to the user.
        """
        spec: Dict[str, Any] = self._make_spec([], "help/er", {"tools": "help/er"})

        filtered: Dict[str, Any] = NameCorrectionConfigFilter().filter_config(spec)

        self.assertEqual("help/er", filtered["tools"][0]["args"]["tools"])
