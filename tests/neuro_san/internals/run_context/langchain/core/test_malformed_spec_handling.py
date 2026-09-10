
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

from unittest import TestCase
import pytest

from neuro_san.internals.run_context.langchain.core.base_model_dictionary_converter \
    import BaseModelDictionaryConverter
from neuro_san.internals.run_context.langchain.core.tool_spec_error import ToolSpecError


class TestMalformedSpecHandling(TestCase):
    """
    Malformed specs produce clean ToolSpecErrors (or honor documented
    contracts) instead of raw AttributeError/TypeError crashes.

    Explicit nulls and wrong-typed values are reachable from both hocon
    registries (pyhocon preserves explicit nulls) and the unvalidated
    JSON function specs external agents send over the network.
    """

    def _convert(self, parameters):
        converter = BaseModelDictionaryConverter("parameters")
        return converter.from_dict(parameters)

    def test_from_dict_none_returns_none(self):
        """The DictionaryConverter contract: None in -> None out."""
        assert self._convert(None) is None

    def test_explicit_null_properties_builds_empty_model(self):
        """
        "properties": null is treated like a missing key, matching how the
        nested-object branch already handles the same case.
        """
        model = self._convert({"properties": None})
        assert model.model_validate({}) is not None

    def test_non_dict_properties_raises_tool_spec_error(self):
        """A wrong-typed "properties" value is a clean spec error, not a crash."""
        with pytest.raises(ToolSpecError, match="'properties' must be an object"):
            self._convert({"properties": "not-a-dict"})

    def test_explicit_null_required_treated_as_no_required(self):
        """An explicit "required": null is treated like a missing key: nothing is required."""
        model = self._convert({
            "properties": {"x": {"type": "string"}},
            "required": None,
        })
        assert model.model_validate({}).x is None

    def test_string_required_raises_tool_spec_error(self):
        """
        A string "required" would substring-match unrelated field names
        (e.g. field "it" against "required": "city"), so it is rejected.
        """
        with pytest.raises(ToolSpecError, match="'required' must be a list"):
            self._convert({
                "properties": {"city": {"type": "string"}, "it": {"type": "string"}},
                "required": "city",
            })

    def test_non_string_required_entries_raise_tool_spec_error(self):
        """
        Non-string "required" entries match nothing in the required test,
        silently making every field optional, so they are rejected.
        """
        with pytest.raises(ToolSpecError, match="'required' must contain only field-name strings"):
            self._convert({
                "properties": {"x": {"type": "string"}},
                "required": [{}],
            })

    def test_non_dict_property_spec_raises_tool_spec_error(self):
        """A property whose spec is not a dict is a clean spec error, not a crash."""
        with pytest.raises(ToolSpecError, match="Property 'x' must be an object"):
            self._convert({"properties": {"x": "string"}})

    def test_missing_type_key_gets_honest_message(self):
        """
        anyOf/enum/$ref-style property specs have no "type" key; the error
        must say so rather than report an unrecognized type named 'None'.
        """
        with pytest.raises(ToolSpecError, match="has no 'type' key"):
            self._convert({
                "properties": {"choice": {"anyOf": [{"type": "string"}, {"type": "int"}]}},
            })

    def test_union_type_list_raises_tool_spec_error(self):
        """
        JSON Schema union lists ("type": ["string", "null"]) used to crash
        the TYPE_LOOKUP dict lookup with an unhashable-key TypeError.
        """
        with pytest.raises(ToolSpecError, match="non-string 'type'"):
            self._convert({
                "properties": {"maybe": {"type": ["string", "null"]}},
            })

    def test_array_without_items_raises_tool_spec_error(self):
        """A missing "items" key used to crash with None.get AttributeError."""
        with pytest.raises(ToolSpecError, match="needs an 'items' object"):
            self._convert({
                "properties": {"tags": {"type": "array"}},
            })

    def test_array_with_string_items_raises_tool_spec_error(self):
        """
        An unresolved commondef reference ("items": "cao_item") can reach
        the converter at runtime via the unvalidated external-agent path.
        """
        with pytest.raises(ToolSpecError, match="needs an 'items' object"):
            self._convert({
                "properties": {"tags": {"type": "array", "items": "cao_item"}},
            })
