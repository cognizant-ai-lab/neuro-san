
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
from unittest.mock import MagicMock

from typing_extensions import override

from leaf_common.filters.string_filter import StringFilter

from neuro_san.internals.utils.mcp_tool_name_policy import McpToolNamePolicy


class TestMcpToolNamePolicy(TestCase):
    """
    Unit tests for McpToolNamePolicy: delegation of the name mapping to its
    StringFilter, the validation helpers, and allow-list matching under
    either spelling.
    """

    @override
    def setUp(self) -> None:
        """
        Creates a policy with the default McpToolNameFilter mapping.
        """
        self.policy: McpToolNamePolicy = McpToolNamePolicy()

    @staticmethod
    def upper_case(in_string: str) -> str:
        """
        Stand-in filter behavior for the injection test.

        :param in_string: The string to transform
        :return: The string in upper case
        """
        return in_string.upper()

    def test_filter_delegates_to_default_filter(self) -> None:
        """
        With no filter injected, the policy maps names the way McpToolNameFilter does.
        """
        self.assertEqual("deep__math_guy", self.policy.filter("deep/math_guy"))
        self.assertEqual("Agent_1", self.policy.filter("Agent.1"))
        self.assertIsNone(self.policy.filter(None))

    def test_injected_filter_drives_mapping_and_matching(self) -> None:
        """
        A different StringFilter can be injected, and the matching methods follow it:
        with an upper-casing filter, "abc" matches a server tool advertised as "ABC".
        """
        upper_filter: MagicMock = MagicMock(spec=StringFilter)
        upper_filter.filter.side_effect = self.upper_case
        policy: McpToolNamePolicy = McpToolNamePolicy(upper_filter)

        self.assertEqual("ABC", policy.filter("abc"))
        self.assertTrue(policy.matches("abc", "ABC"))
        self.assertFalse(policy.matches("abc", "XYZ"))
        self.assertEqual(["ABC"], policy.select_allowed(["abc"], ["ABC", "XYZ"]))
        # The default "/" mapping is not in play with this filter.
        self.assertFalse(policy.matches("deep/math_guy", "deep__math_guy"))

    def test_is_valid_tool_name_accepts_valid(self) -> None:
        """
        Letters, digits, underscore and hyphen pass validation.
        """
        self.assertTrue(McpToolNamePolicy.is_valid_tool_name("deep__math_guy-2"))

    def test_is_valid_tool_name_rejects_unsafe_chars(self) -> None:
        """
        A raw registry path with "/", and names containing "." or whitespace, fail validation.
        """
        self.assertFalse(McpToolNamePolicy.is_valid_tool_name("deep/math_guy"))
        self.assertFalse(McpToolNamePolicy.is_valid_tool_name("Agent.1"))
        self.assertFalse(McpToolNamePolicy.is_valid_tool_name("Agent 2"))

    def test_is_valid_tool_name_rejects_none_and_empty(self) -> None:
        """
        Neither None nor the empty string is a valid tool name.
        """
        self.assertFalse(McpToolNamePolicy.is_valid_tool_name(None))
        self.assertFalse(McpToolNamePolicy.is_valid_tool_name(""))

    def test_is_valid_tool_name_length_boundary(self) -> None:
        """
        128 characters is the longest valid name; 129 is rejected.
        """
        self.assertTrue(McpToolNamePolicy.is_valid_tool_name("a" * 128))
        self.assertFalse(McpToolNamePolicy.is_valid_tool_name("a" * 129))

    def test_is_over_soft_limit(self) -> None:
        """
        Exactly 64 characters is within the OpenAI soft limit, 65 is over it,
        and None has no length so it is not over the limit.
        """
        self.assertFalse(McpToolNamePolicy.is_over_soft_limit("a" * 64))
        self.assertTrue(McpToolNamePolicy.is_over_soft_limit("a" * 65))
        self.assertFalse(McpToolNamePolicy.is_over_soft_limit(None))

    def test_matches_accepts_either_spelling(self) -> None:
        """
        An entry matches a server tool when written exactly as advertised, as the
        provider-safe name of a "/" tool, or with the original "/" against a server
        that has already renamed the tool.
        """
        self.assertTrue(self.policy.matches("deep/math_guy", "deep/math_guy"))
        self.assertTrue(self.policy.matches("deep__math_guy", "deep/math_guy"))
        self.assertTrue(self.policy.matches("deep/math_guy", "deep__math_guy"))

    def test_matches_rejects_unrelated_name(self) -> None:
        """
        An entry that matches under no spelling does not match.
        """
        self.assertFalse(self.policy.matches("deep/math_guy", "deep/music_nerd"))

    def test_matches_is_symmetric_for_every_unsafe_character(self) -> None:
        """
        An entry written with any unsafe character matches the tool a renaming
        server advertises under the mangled spelling, not only entries with "/".
        """
        self.assertTrue(self.policy.matches("a.b", "a_b"))
        self.assertTrue(self.policy.matches("a b", "a_b"))
        self.assertTrue(self.policy.matches("a/b.c", "a__b_c"))
        # The mangled spellings still have to be the same.
        self.assertFalse(self.policy.matches("a.b", "a-b"))
        self.assertFalse(self.policy.matches("a.b", "a__b"))

    def test_resolve_prefers_exact_spelling(self) -> None:
        """
        When a server offers both "a/b" and "a__b", each entry resolves to the tool it spells exactly.
        """
        originals: List[str] = ["a/b", "a__b"]
        self.assertEqual("a/b", self.policy.resolve("a/b", originals))
        self.assertEqual("a__b", self.policy.resolve("a__b", originals))
        # The same holds for other unsafe characters: an exact "a.b" is not
        # confused with a literal "a_b" the server also offers.
        self.assertEqual("a.b", self.policy.resolve("a.b", ["a_b", "a.b"]))
        self.assertEqual("a_b", self.policy.resolve("a_b", ["a_b", "a.b"]))

    def test_resolve_falls_back_to_safe_spelling(self) -> None:
        """
        Without an exact match an entry resolves to the first tool it matches under
        the provider-safe spelling, and to None when nothing matches or the server
        advertised nothing.
        """
        self.assertEqual("a__b", self.policy.resolve("a/b", ["a__b"]))
        self.assertEqual("a/b", self.policy.resolve("a__b", ["a/b"]))
        self.assertIsNone(self.policy.resolve("a/b", ["other"]))
        self.assertIsNone(self.policy.resolve("a/b", None))
        self.assertIsNone(self.policy.resolve("a/b", []))

    def test_select_allowed_prefers_exact_spelling(self) -> None:
        """
        An allow list naming "a/b" against a server offering both "a/b" and "a__b"
        selects only "a/b", and one naming "a__b" selects only "a__b", so the caller
        never has to choose between two tools the author did not both ask for.
        """
        originals: List[str] = ["a/b", "a__b"]
        self.assertEqual(["a/b"], self.policy.select_allowed(["a/b"], originals))
        self.assertEqual(["a__b"], self.policy.select_allowed(["a__b"], originals))

    def test_select_allowed_keeps_server_order_without_duplicates(self) -> None:
        """
        The selection follows the server's order, not the allow list's, and two
        entries that resolve to the same tool yield it once.
        """
        allowed: List[str] = ["deep__music_nerd", "deep/math_guy", "deep/music_nerd"]
        originals: List[str] = ["deep/math_guy", "deep/music_nerd", "other"]
        self.assertEqual(["deep/math_guy", "deep/music_nerd"],
                         self.policy.select_allowed(allowed, originals))

    def test_select_allowed_degenerate_lists(self) -> None:
        """
        A None or empty allow list selects nothing, as do entries matching no tool
        or a server that advertised nothing.
        """
        self.assertEqual([], self.policy.select_allowed(None, ["deep/math_guy"]))
        self.assertEqual([], self.policy.select_allowed([], ["deep/math_guy"]))
        self.assertEqual([], self.policy.select_allowed(["nope"], ["deep/math_guy"]))
        self.assertEqual([], self.policy.select_allowed(["deep/math_guy"], None))
        self.assertEqual([], self.policy.select_allowed(["deep/math_guy"], []))

    def test_find_unmatched_reports_only_unmatched_in_order(self) -> None:
        """
        Entries matching under some spelling are not reported; the rest come back
        in the order they were written, and an all-matching list yields nothing.
        """
        allowed: List[str] = ["zeta/typo", "deep__math_guy", "alpha.typo", "deep/music_nerd"]
        originals: List[str] = ["deep/math_guy", "deep/music_nerd"]
        self.assertEqual(["zeta/typo", "alpha.typo"], self.policy.find_unmatched(allowed, originals))
        self.assertEqual([], self.policy.find_unmatched(["deep/math_guy", "deep__music_nerd"], originals))

    def test_find_unmatched_degenerate_lists(self) -> None:
        """
        None or empty allow lists produce no unmatched entries; when the server
        advertises nothing, every entry is unmatched.
        """
        self.assertEqual([], self.policy.find_unmatched(None, ["deep/math_guy"]))
        self.assertEqual([], self.policy.find_unmatched([], ["deep/math_guy"]))
        allowed: List[str] = ["deep/math_guy", "other"]
        self.assertEqual(allowed, self.policy.find_unmatched(allowed, None))
        self.assertEqual(allowed, self.policy.find_unmatched(allowed, []))
