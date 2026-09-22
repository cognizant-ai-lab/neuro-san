
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
from typing import List

from unittest import TestCase

from typing_extensions import override

from leaf_common.filters.string_filter import StringFilter

from neuro_san.internals.utils.mcp_tool_name_filter import McpToolNameFilter


class TestMcpToolNameFilter(TestCase):
    """
    Unit tests for McpToolNameFilter: the network-name to provider-safe
    tool-name mapping.
    """

    @override
    def setUp(self) -> None:
        """
        Creates the filter under test.
        """
        self.tool_filter: StringFilter = McpToolNameFilter()

    def test_filter_maps_slashes(self) -> None:
        """
        Every "/" in a registry path becomes a double underscore, not just the first.
        """
        self.assertEqual("deep__math_guy", self.tool_filter.filter("deep/math_guy"))
        self.assertEqual("a__b__c", self.tool_filter.filter("a/b/c"))

    def test_filter_leaves_safe_name_untouched(self) -> None:
        """
        A name already made of letters, digits, underscore and hyphen is returned as-is.
        """
        safe_name: str = "Music_nerd-pro9"
        self.assertEqual(safe_name, self.tool_filter.filter(safe_name))

    def test_filter_passes_none_and_empty_through(self) -> None:
        """
        None and the empty string come back unchanged so optional values can be fed in directly.
        """
        self.assertIsNone(self.tool_filter.filter(None))
        self.assertEqual("", self.tool_filter.filter(""))

    def test_filter_replaces_unsafe_chars(self) -> None:
        """
        ".", whitespace and non-ASCII letters (which str.isalnum() accepts) each become one underscore.
        """
        self.assertEqual("Agent_1", self.tool_filter.filter("Agent.1"))
        self.assertEqual("Agent_2", self.tool_filter.filter("Agent 2"))
        self.assertEqual("caf_", self.tool_filter.filter("café"))

    def test_filter_is_idempotent(self) -> None:
        """
        Applying the mapping twice yields the same result as applying it once,
        so a name fixed on the server side is not mangled again by the client.
        """
        samples: List[str] = ["deep/math_guy", "a/b/c", "Agent.1", "Agent 2", "plain", "x__y", "a-b"]
        for sample in samples:
            once: str = self.tool_filter.filter(sample)
            twice: str = self.tool_filter.filter(once)
            self.assertEqual(once, twice, f"mapping not idempotent for {sample!r}")

    def test_is_safe_char(self) -> None:
        """
        ASCII letters, digits, underscore and hyphen are safe; "/", ".", space and non-ASCII are not.
        """
        for char in ("a", "Z", "7", "_", "-"):
            self.assertTrue(McpToolNameFilter.is_safe_char(char), char)
        for char in ("/", ".", " ", "é", "²"):
            self.assertFalse(McpToolNameFilter.is_safe_char(char), char)
