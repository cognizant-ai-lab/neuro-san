
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

from neuro_san.internals.validation.network.lint_network_validator import LintNetworkValidator


class TestFindUnusedCommondefs(unittest.TestCase):
    """
    Unit tests for the unused-commondefs lint check.
    """

    def test_replacement_value_substring_does_not_count_as_used(self):
        """A replacement_values key embedded in a longer string is not used."""
        raw_config = {
            "commondefs": {"replacement_values": {"my_key": {"type": "string"}}},
            "tools": [{"name": "agent", "instructions": "my_key_extended is not the same"}],
        }
        validator = LintNetworkValidator(raw_config=raw_config)
        warnings = validator.validate({})
        self.assertEqual(len(warnings), 1)
        self.assertIn("replacement_values.my_key", warnings[0])

    def test_used_replacement_string_is_clean(self):
        """A replacement_strings entry referenced via {key} is not flagged."""
        raw_config = {
            "commondefs": {"replacement_strings": {"operation": "addition"}},
            "tools": [{"name": "agent", "instructions": "Perform the {operation} operation."}],
        }
        validator = LintNetworkValidator(raw_config=raw_config)
        self.assertEqual(validator.validate({}), [])

    def test_unused_replacement_string_is_flagged(self):
        """A replacement_strings entry never referenced as {key} is flagged."""
        raw_config = {
            "commondefs": {"replacement_strings": {"operation": "addition"}},
            "tools": [{"name": "agent", "instructions": "Nothing to see here."}],
        }
        validator = LintNetworkValidator(raw_config=raw_config)
        warnings = validator.validate({})
        self.assertEqual(len(warnings), 1)
        self.assertIn("replacement_strings.operation", warnings[0])

    def test_used_replacement_value_is_clean(self):
        """A replacement_values entry referenced as a bare value is not flagged."""
        raw_config = {
            "commondefs": {"replacement_values": {"cao_item": {"type": "string"}}},
            "tools": [{"name": "agent", "function": {"parameters": "cao_item"}}],
        }
        validator = LintNetworkValidator(raw_config=raw_config)
        self.assertEqual(validator.validate({}), [])

    def test_unused_replacement_value_is_flagged(self):
        """A replacement_values entry never used as a bare value is flagged."""
        raw_config = {
            "commondefs": {"replacement_values": {"cao_item": {"type": "string"}}},
            "tools": [{"name": "agent", "instructions": "Nothing to see here."}],
        }
        validator = LintNetworkValidator(raw_config=raw_config)
        warnings = validator.validate({})
        self.assertEqual(len(warnings), 1)
        self.assertIn("replacement_values.cao_item", warnings[0])

    def test_cross_referenced_commondef_is_clean(self):
        """A replacement_strings entry used by another entry still counts as used."""
        raw_config = {
            "commondefs": {
                "replacement_strings": {
                    "name": "Fred",
                    "greeting": "Hello, {name}!",
                }
            },
            "tools": [{"name": "agent", "instructions": "{greeting}"}],
        }
        validator = LintNetworkValidator(raw_config=raw_config)
        self.assertEqual(validator.validate({}), [])

    def test_non_dict_raw_config_is_clean(self):
        """A malformed (non-dict) raw config produces no warnings."""
        validator = LintNetworkValidator(raw_config=None)
        self.assertEqual(validator.validate({}), [])


class TestFindUnresolvedReplacementStrings(unittest.TestCase):
    """
    Unit tests for the unresolved-placeholder lint check.
    """

    def test_multiple_distinct_placeholders_each_reported(self):
        """Two different unresolved placeholders each get their own warning."""
        resolved_config = {
            "tools": [{"name": "agent", "instructions": "Use {foo} and {bar} together."}]
        }
        validator = LintNetworkValidator()
        warnings = validator.validate(resolved_config)
        self.assertEqual(len(warnings), 2)
        combined = " ".join(warnings)
        self.assertIn("{foo}", combined)
        self.assertIn("{bar}", combined)

    def test_leftover_placeholder_is_flagged(self):
        """A {word}-shaped token surviving substitution is flagged."""
        resolved_config = {
            "tools": [{"name": "agent", "instructions": "Perform the {operation} operation."}]
        }
        validator = LintNetworkValidator()
        warnings = validator.validate(resolved_config)
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
        validator = LintNetworkValidator()
        warnings = validator.validate(resolved_config)
        self.assertEqual(len(warnings), 1)

    def test_regex_quantifier_is_not_flagged(self):
        """A {3}-shaped regex quantifier should not be mistaken for a placeholder."""
        resolved_config = {
            "tools": [{"name": "agent", "instructions": "[a-zA-Z0-9]{3}-[a-zA-Z0-9]{4}"}]
        }
        self.assertEqual(LintNetworkValidator().validate(resolved_config), [])

    def test_double_braces_are_not_flagged(self):
        """A {{word}} placeholder used by LangChain templates is not flagged."""
        resolved_config = {
            "tools": [{"name": "agent", "instructions": "Summarize: {{messages}}"}]
        }
        self.assertEqual(LintNetworkValidator().validate(resolved_config), [])

    def test_only_instructions_and_description_scanned(self):
        """A {word} token in a field other than instructions/description is not flagged."""
        resolved_config = {
            "tools": [{"name": "agent", "instructions": "OK", "args": {"url": "/{path}/api"}}]
        }
        self.assertEqual(LintNetworkValidator().validate(resolved_config), [])

    def test_nested_function_description_is_not_scanned(self):
        """A {word} token inside function.description is not scanned (only top-level fields)."""
        resolved_config = {
            "tools": [{"name": "agent", "function": {"description": "Perform {action}"}}]
        }
        self.assertEqual(LintNetworkValidator().validate(resolved_config), [])

    def test_top_level_description_is_scanned(self):
        """A {word} token in a tool's top-level 'description' field is flagged."""
        resolved_config = {
            "tools": [{"name": "agent", "description": "Does the {action} thing"}]
        }
        warnings = LintNetworkValidator().validate(resolved_config)
        self.assertEqual(len(warnings), 1)
        self.assertIn("{action}", warnings[0])


class TestIndividualCheckMethods(unittest.TestCase):
    """
    Tests for the individual check methods called directly.
    """

    def test_find_unused_commondefs_returns_warnings(self):
        """find_unused_commondefs() returns warnings independently of validate()."""
        raw_config = {
            "commondefs": {"replacement_strings": {"stale": "old"}},
            "tools": [{"name": "agent", "instructions": "Nothing."}],
        }
        validator = LintNetworkValidator(raw_config=raw_config)
        warnings = validator.find_unused_commondefs()
        self.assertEqual(len(warnings), 1)
        self.assertIn("stale", warnings[0])

    def test_find_unresolved_placeholders_returns_warnings(self):
        """find_unresolved_placeholders() returns warnings independently of validate()."""
        resolved_config = {
            "tools": [{"name": "agent", "instructions": "Do {something}."}]
        }
        warnings = LintNetworkValidator.find_unresolved_placeholders(resolved_config)
        self.assertEqual(len(warnings), 1)
        self.assertIn("{something}", warnings[0])


if __name__ == "__main__":
    unittest.main()
