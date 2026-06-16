
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
"""
Unit tests for ConfigUtil.get_bool().

LLM policies and other config-driven sites delegate boolean-key reads
to ConfigUtil.get_bool(), so it has to accept the common boolean-like
forms surfaced by HOCON / JSON / env configs and fall back safely on
unrecognized input.
"""

from neuro_san.internals.utils.config_util import ConfigUtil


class TestConfigUtilGetBool:
    """
    Verifies ConfigUtil.get_bool() across:
      - absence (returns default)
      - native bool (returned as-is)
      - recognized string forms (true/yes vs false/no, case-insensitive)
      - int (0 is False; non-zero is True)
      - unrecognized values (returns default)
    """

    # ---- Defaults / absence ---------------------------------------------------

    def test_absent_key_returns_default_false(self):
        """When the key is missing and no default is supplied, returns False."""
        assert ConfigUtil.get_bool({}, "streaming") is False

    def test_absent_key_returns_default_true_when_supplied(self):
        """When the key is missing, the explicit default is returned."""
        assert ConfigUtil.get_bool({}, "streaming", default=True) is True

    def test_unrelated_key_does_not_affect_lookup(self):
        """Only the requested key is consulted; siblings are ignored."""
        assert ConfigUtil.get_bool({"other": True}, "streaming") is False

    # ---- Native bool ----------------------------------------------------------

    def test_explicit_true_returns_true(self):
        """A literal Python True is returned as True."""
        assert ConfigUtil.get_bool({"streaming": True}, "streaming") is True

    def test_explicit_false_returns_false(self):
        """A literal Python False is returned as False."""
        assert ConfigUtil.get_bool({"streaming": False}, "streaming") is False

    # ---- String forms ---------------------------------------------------------

    def test_string_true_yes_resolve_to_true(self):
        """"true" / "yes" (case-insensitive, surrounding whitespace) -> True."""
        assert ConfigUtil.get_bool({"k": "true"}, "k") is True
        assert ConfigUtil.get_bool({"k": "TRUE"}, "k") is True
        assert ConfigUtil.get_bool({"k": " Yes "}, "k") is True

    def test_string_false_no_resolve_to_false(self):
        """"false" / "no" (case-insensitive, surrounding whitespace) -> False."""
        assert ConfigUtil.get_bool({"k": "false"}, "k") is False
        assert ConfigUtil.get_bool({"k": "NO"}, "k") is False
        assert ConfigUtil.get_bool({"k": " False "}, "k") is False

    def test_unrecognized_string_returns_default(self):
        """Strings that aren't yes/no/true/false fall back to default."""
        assert ConfigUtil.get_bool({"k": "maybe"}, "k") is False
        assert ConfigUtil.get_bool({"k": "maybe"}, "k", default=True) is True
        assert ConfigUtil.get_bool({"k": ""}, "k") is False

    # ---- Integer forms --------------------------------------------------------

    def test_nonzero_int_is_true(self):
        """Any non-zero int is interpreted as True."""
        assert ConfigUtil.get_bool({"k": 1}, "k") is True
        assert ConfigUtil.get_bool({"k": -1}, "k") is True
        assert ConfigUtil.get_bool({"k": 42}, "k") is True

    def test_zero_int_is_false(self):
        """Zero is interpreted as False."""
        assert ConfigUtil.get_bool({"k": 0}, "k") is False

    # ---- Unrecognized values --------------------------------------------------

    def test_none_value_returns_default(self):
        """A literal None (e.g. HOCON `null`) falls back to default."""
        assert ConfigUtil.get_bool({"k": None}, "k") is False
        assert ConfigUtil.get_bool({"k": None}, "k", default=True) is True

    def test_list_value_returns_default(self):
        """Lists are not recognized; fall back to default."""
        assert ConfigUtil.get_bool({"k": ["true"]}, "k") is False
        assert ConfigUtil.get_bool({"k": []}, "k") is False

    def test_dict_value_returns_default(self):
        """Dicts are not recognized; fall back to default."""
        assert ConfigUtil.get_bool({"k": {"true": True}}, "k") is False
