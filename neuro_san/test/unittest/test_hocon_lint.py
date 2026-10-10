
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

import unittest

from neuro_san.internals.validation.hocon_lint import find_unresolved_replacement_strings
from neuro_san.internals.validation.hocon_lint import find_unset_allow_sly_data_keys
from neuro_san.internals.validation.hocon_lint import find_unused_commondefs


class TestFindUnusedCommondefs(unittest.TestCase):
    """
    Unit tests for find_unused_commondefs().
    """

    def test_replacement_value_substring_does_not_count_as_used(self):
        """A replacement_values key that only appears embedded inside a longer string
        value is not treated as used — substitution requires an exact bare-string match."""
        raw_config = {
            "commondefs": {"replacement_values": {"my_key": {"type": "string"}}},
            "tools": [{"name": "agent", "instructions": "my_key_extended is not the same"}],
        }
        warnings = find_unused_commondefs(raw_config)
        self.assertEqual(len(warnings), 1)
        self.assertIn("replacement_values.my_key", warnings[0])

    def test_used_replacement_string_is_clean(self):
        """A replacement_strings entry referenced via {key} anywhere is not flagged."""
        raw_config = {
            "commondefs": {"replacement_strings": {"operation": "addition"}},
            "tools": [{"name": "agent", "instructions": "Perform the {operation} operation."}],
        }
        self.assertEqual(find_unused_commondefs(raw_config), [])

    def test_unused_replacement_string_is_flagged(self):
        """A replacement_strings entry never referenced as {key} is flagged."""
        raw_config = {
            "commondefs": {"replacement_strings": {"operation": "addition"}},
            "tools": [{"name": "agent", "instructions": "Nothing to see here."}],
        }
        warnings = find_unused_commondefs(raw_config)
        self.assertEqual(len(warnings), 1)
        self.assertIn("replacement_strings.operation", warnings[0])

    def test_used_replacement_value_is_clean(self):
        """A replacement_values entry referenced as a bare value anywhere is not flagged."""
        raw_config = {
            "commondefs": {"replacement_values": {"cao_item": {"type": "string"}}},
            "tools": [{"name": "agent", "function": {"parameters": "cao_item"}}],
        }
        self.assertEqual(find_unused_commondefs(raw_config), [])

    def test_unused_replacement_value_is_flagged(self):
        """A replacement_values entry never used as a bare value is flagged."""
        raw_config = {
            "commondefs": {"replacement_values": {"cao_item": {"type": "string"}}},
            "tools": [{"name": "agent", "instructions": "Nothing to see here."}],
        }
        warnings = find_unused_commondefs(raw_config)
        self.assertEqual(len(warnings), 1)
        self.assertIn("replacement_values.cao_item", warnings[0])

    def test_cross_referenced_commondef_is_clean(self):
        """A replacement_strings entry only used by another commondefs entry still counts as used."""
        raw_config = {
            "commondefs": {
                "replacement_strings": {
                    "name": "Fred",
                    "greeting": "Hello, {name}!",
                }
            },
            "tools": [{"name": "agent", "instructions": "{greeting}"}],
        }
        self.assertEqual(find_unused_commondefs(raw_config), [])

    def test_non_dict_raw_config_is_clean(self):
        """A malformed (non-dict) config just produces no warnings rather than raising."""
        self.assertEqual(find_unused_commondefs(None), [])


class TestFindUnresolvedReplacementStrings(unittest.TestCase):
    """
    Unit tests for find_unresolved_replacement_strings().
    """

    def test_multiple_distinct_placeholders_each_reported(self):
        """Two different unresolved placeholders in the same instruction each get their own warning."""
        resolved_config = {
            "tools": [{"name": "agent", "instructions": "Use {foo} and {bar} together."}]
        }
        warnings = find_unresolved_replacement_strings(resolved_config)
        self.assertEqual(len(warnings), 2)
        combined = " ".join(warnings)
        self.assertIn("{foo}", combined)
        self.assertIn("{bar}", combined)

    def test_leftover_placeholder_is_flagged(self):
        """A {word}-shaped token surviving substitution is flagged."""
        resolved_config = {"tools": [{"name": "agent", "instructions": "Perform the {operation} operation."}]}
        warnings = find_unresolved_replacement_strings(resolved_config)
        self.assertEqual(len(warnings), 1)
        self.assertIn("{operation}", warnings[0])

    def test_duplicate_placeholder_reported_once(self):
        """The same leftover token appearing more than once is only reported once."""
        resolved_config = {
            "tools": [
                {"name": "agent1", "instructions": "Use {operation} here."},
                {"name": "agent2", "instructions": "And {operation} here too."},
            ]
        }
        warnings = find_unresolved_replacement_strings(resolved_config)
        self.assertEqual(len(warnings), 1)

    def test_regex_quantifier_is_not_flagged(self):
        """A {3}-shaped regex quantifier in a string should not be mistaken for a placeholder."""
        resolved_config = {"tools": [{"name": "agent", "args": {"detector": "[a-zA-Z0-9]{3}-[a-zA-Z0-9]{4}"}}]}
        self.assertEqual(find_unresolved_replacement_strings(resolved_config), [])

    def test_commondefs_section_itself_is_not_scanned(self):
        """
        Only the "tools" subtree is substituted by the filter chain, so a commondefs
        definition that still contains a cross-referencing brace (because the raw,
        unfiltered commondefs dict is carried through to the resolved config as-is)
        must not be flagged.
        """
        resolved_config = {
            "commondefs": {"replacement_strings": {"name": "Fred", "greeting": "Hello, {name}!"}},
            "tools": [{"name": "agent", "instructions": "Hello, Fred!"}],
        }
        self.assertEqual(find_unresolved_replacement_strings(resolved_config), [])


class TestFindUnsetAllowSlyDataKeys(unittest.TestCase):
    """
    Unit tests for find_unset_allow_sly_data_keys().
    """

    def test_declared_key_in_list_form_is_clean(self):
        """A sly_data key declared via sly_data_schema and referenced via list form is not flagged."""
        resolved_config = {
            "tools": [
                {
                    "name": "agent",
                    "function": {"sly_data_schema": {"type": "object", "properties": {"x": {"type": "float"}}}},
                    "allow": {"to_downstream": {"sly_data": ["x"]}},
                }
            ]
        }
        self.assertEqual(find_unset_allow_sly_data_keys(resolved_config), [])

    def test_declared_key_in_dict_form_is_clean(self):
        """A sly_data key declared via sly_data_output_schema and referenced via dict form is not flagged."""
        resolved_config = {
            "tools": [
                {
                    "name": "agent",
                    "function": {
                        "sly_data_output_schema": {"type": "object", "properties": {"equals": {"type": "float"}}}
                    },
                    "allow": {"to_upstream": {"sly_data": {"equals": True}}},
                }
            ]
        }
        self.assertEqual(find_unset_allow_sly_data_keys(resolved_config), [])

    def test_undeclared_key_is_flagged(self):
        """A sly_data key with no matching schema property anywhere is flagged."""
        resolved_config = {
            "tools": [
                {
                    "name": "agent",
                    "allow": {"to_upstream": {"sly_data": ["mystery_key"]}},
                }
            ]
        }
        warnings = find_unset_allow_sly_data_keys(resolved_config)
        self.assertEqual(len(warnings), 1)
        self.assertIn("mystery_key", warnings[0])
        self.assertIn("agent", warnings[0])

    def test_key_declared_by_a_different_agent_still_counts(self):
        """Schema declarations anywhere in the network satisfy an allow reference in any agent."""
        resolved_config = {
            "tools": [
                {
                    "name": "front_man",
                    "allow": {"to_upstream": {"sly_data": ["equals"]}},
                },
                {
                    "name": "calculator",
                    "function": {
                        "sly_data_output_schema": {"type": "object", "properties": {"equals": {"type": "float"}}}
                    },
                },
            ]
        }
        self.assertEqual(find_unset_allow_sly_data_keys(resolved_config), [])

    def test_translation_target_name_is_not_checked(self):
        """The renamed/translated target of a dict-form entry is not itself checked for existence."""
        resolved_config = {
            "tools": [
                {
                    "name": "agent",
                    "function": {"sly_data_schema": {"type": "object", "properties": {"my_session": {}}}},
                    "allow": {"to_downstream": {"sly_data": {"my_session": "session_id"}}},
                }
            ]
        }
        self.assertEqual(find_unset_allow_sly_data_keys(resolved_config), [])

    def test_network_level_sly_data_schema_counts(self):
        """A sly_data_schema declared at the top level of the network config (not
        nested inside any tool's 'function') still satisfies allow references to its keys."""
        resolved_config = {
            "sly_data_schema": {
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
            },
            "tools": [
                {
                    "name": "agent",
                    "allow": {"to_downstream": {"sly_data": ["session_id"]}},
                }
            ],
        }
        self.assertEqual(find_unset_allow_sly_data_keys(resolved_config), [])

    def test_from_downstream_direction_is_checked(self):
        """allow.from_downstream.sly_data is checked just like to_downstream and to_upstream."""
        resolved_config = {
            "tools": [
                {
                    "name": "orchestrator",
                    "allow": {"from_downstream": {"sly_data": ["result_score"]}},
                }
            ]
        }
        warnings = find_unset_allow_sly_data_keys(resolved_config)
        self.assertEqual(len(warnings), 1)
        self.assertIn("result_score", warnings[0])
        self.assertIn("orchestrator", warnings[0])

    def test_mixed_declared_and_undeclared_only_undeclared_flagged(self):
        """When an allow block references both a declared and an undeclared key,
        only the undeclared key is flagged — the declared one must not appear in warnings."""
        resolved_config = {
            "tools": [
                {
                    "name": "agent",
                    "function": {
                        "sly_data_schema": {
                            "type": "object",
                            "properties": {"good_key": {"type": "string"}},
                        }
                    },
                    "allow": {"to_upstream": {"sly_data": ["good_key", "bad_key"]}},
                }
            ]
        }
        warnings = find_unset_allow_sly_data_keys(resolved_config)
        self.assertEqual(len(warnings), 1)
        self.assertIn("bad_key", warnings[0])
        self.assertNotIn("good_key", warnings[0])


if __name__ == "__main__":
    unittest.main()
