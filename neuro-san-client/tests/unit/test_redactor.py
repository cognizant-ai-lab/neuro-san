
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
"""Unit tests for neuro_san_client.redactor."""
from __future__ import annotations

import pytest

from neuro_san_client.redactor import redact


SLY = {"passenger_email": "bob@example.com",
       "browser_secret": "must-not-leak",
       "last_booking_code": "HOLD-XYZ"}


CONFIG_KEYS = ["allow.to_downstream.sly_data"]


class TestRedactDenyByDefault:
    def test_missing_spec(self):
        assert redact(None, SLY, CONFIG_KEYS) == {}

    def test_empty_spec(self):
        assert redact({}, SLY, CONFIG_KEYS) == {}

    def test_missing_path(self):
        # spec exists but has no allow.* block
        assert redact({"name": "foo"}, SLY, CONFIG_KEYS) == {}

    def test_explicit_false(self):
        spec = {"allow": {"to_downstream": {"sly_data": False}}}
        assert redact(spec, SLY, CONFIG_KEYS) == {}

    def test_empty_dict(self):
        spec = {"allow": {"to_downstream": {"sly_data": {}}}}
        assert redact(spec, SLY, CONFIG_KEYS) == {}

    def test_empty_list(self):
        spec = {"allow": {"to_downstream": {"sly_data": []}}}
        assert redact(spec, SLY, CONFIG_KEYS) == {}


class TestRedactAllowAll:
    def test_true_passes_everything(self):
        spec = {"allow": {"to_downstream": {"sly_data": True}}}
        out = redact(spec, SLY, CONFIG_KEYS)
        assert out == SLY
        # Must be a copy, not the original (caller should be free to mutate).
        assert out is not SLY


class TestRedactListForm:
    def test_simple_allowlist(self):
        spec = {"allow": {"to_downstream": {"sly_data": ["passenger_email"]}}}
        out = redact(spec, SLY, CONFIG_KEYS)
        assert out == {"passenger_email": "bob@example.com"}

    def test_multiple_keys(self):
        spec = {"allow": {"to_downstream":
                          {"sly_data": ["passenger_email", "last_booking_code"]}}}
        out = redact(spec, SLY, CONFIG_KEYS)
        assert out == {
            "passenger_email": "bob@example.com",
            "last_booking_code": "HOLD-XYZ",
        }

    def test_listed_key_missing_from_sly_is_skipped(self):
        spec = {"allow": {"to_downstream": {"sly_data": ["not_in_sly"]}}}
        assert redact(spec, SLY, CONFIG_KEYS) == {}

    def test_list_with_non_string_values_ignored(self):
        spec = {"allow": {"to_downstream":
                          {"sly_data": ["passenger_email", 42, None]}}}
        out = redact(spec, SLY, CONFIG_KEYS)
        assert out == {"passenger_email": "bob@example.com"}


class TestRedactDictForm:
    def test_explicit_true_allows(self):
        spec = {"allow": {"to_downstream":
                          {"sly_data": {"passenger_email": True}}}}
        out = redact(spec, SLY, CONFIG_KEYS)
        assert out == {"passenger_email": "bob@example.com"}

    def test_explicit_false_denies(self):
        spec = {"allow": {"to_downstream": {"sly_data": {
            "passenger_email": True,
            "browser_secret": False,
        }}}}
        out = redact(spec, SLY, CONFIG_KEYS)
        assert out == {"passenger_email": "bob@example.com"}

    def test_string_value_renames(self):
        # The dict form's most powerful feature: value is the destination key.
        spec = {"allow": {"to_downstream": {"sly_data": {
            "passenger_email": "user_email",
        }}}}
        out = redact(spec, SLY, CONFIG_KEYS)
        assert out == {"user_email": "bob@example.com"}

    def test_dict_with_missing_keys_skips(self):
        spec = {"allow": {"to_downstream": {"sly_data": {
            "passenger_email": True,
            "absent": True,
        }}}}
        out = redact(spec, SLY, CONFIG_KEYS)
        assert out == {"passenger_email": "bob@example.com"}

    def test_unknown_value_type_denies(self):
        spec = {"allow": {"to_downstream": {"sly_data": {
            "passenger_email": 42,  # neither bool nor str: defensively denied
        }}}}
        out = redact(spec, SLY, CONFIG_KEYS)
        assert out == {}


class TestPrecedence:
    def test_later_config_key_wins(self):
        # Config keys are listed in *increasing* precedence. The second wins.
        spec = {
            "allow": {
                "sly_data": ["browser_secret"],         # generic
                "to_downstream": {
                    "sly_data": ["passenger_email"],     # specific
                },
            }
        }
        config_keys = ["allow.sly_data", "allow.to_downstream.sly_data"]
        out = redact(spec, SLY, config_keys)
        assert out == {"passenger_email": "bob@example.com"}

    def test_falls_back_to_earlier_when_later_missing(self):
        spec = {"allow": {"sly_data": ["passenger_email"]}}
        config_keys = ["allow.sly_data", "allow.to_downstream.sly_data"]
        out = redact(spec, SLY, config_keys)
        assert out == {"passenger_email": "bob@example.com"}


class TestAllowEmptyDict:
    def test_empty_returns_dict_by_default(self):
        out = redact({}, SLY, CONFIG_KEYS)
        assert out == {}

    def test_empty_returns_none_when_flag_set(self):
        out = redact({}, SLY, CONFIG_KEYS, allow_empty_dict=False)
        assert out is None

    def test_nonempty_unaffected_by_flag(self):
        spec = {"allow": {"to_downstream": {"sly_data": True}}}
        out = redact(spec, SLY, CONFIG_KEYS, allow_empty_dict=False)
        assert out == SLY


class TestSlyDataValidation:
    def test_non_dict_sly_data_treated_as_empty(self):
        spec = {"allow": {"to_downstream": {"sly_data": True}}}
        out = redact(spec, "not a dict", CONFIG_KEYS)  # type: ignore[arg-type]
        assert out == {}

    def test_none_sly_data(self):
        spec = {"allow": {"to_downstream": {"sly_data": True}}}
        out = redact(spec, None, CONFIG_KEYS)
        assert out == {}


class TestPreservesValueTypes:
    def test_values_can_be_any_type(self):
        sly = {
            "string": "hi",
            "number": 42,
            "list": [1, 2, 3],
            "dict": {"nested": True},
            "bool": False,
        }
        spec = {"allow": {"to_downstream": {"sly_data": True}}}
        out = redact(spec, sly, CONFIG_KEYS)
        assert out == sly
