
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

import pytest

from pydantic import BaseModel
from pydantic import ValidationError

from neuro_san.internals.run_context.langchain.core.base_model_dictionary_converter \
    import BaseModelDictionaryConverter
from neuro_san.internals.run_context.langchain.core.tool_spec_error import ToolSpecError


class TestBaseModelDictionaryConverter:
    """
    Test cases for the OpenAI-function-spec -> pydantic BaseModel conversion,
    with emphasis on the handling of bare "object" parameters (no properties).

    Bare objects map to Dict[str, Any] rather than Any so that the JSON
    schema advertised to LLM providers declares a real object type.  A bare
    Any produced an empty schema ({}), which langchain-google-genai degrades
    to a STRING declaration - Gemini then sends JSON-encoded strings where
    tools expect dictionaries.
    """

    def _convert(self, parameters: Dict[str, Any]) -> BaseModel:
        converter = BaseModelDictionaryConverter("parameters")
        return converter.from_dict(parameters)

    def test_bare_object_accepts_dict_as_plain_dict(self):
        """A well-formed dict argument reaches the tool as the same plain dict."""
        model = self._convert({
            "properties": {"blob": {"type": "object"}},
            "required": ["blob"],
        })
        payload = {"a": 1, "b": {"c": 2}}
        instance = model.model_validate({"blob": payload})
        assert instance.blob == payload
        assert isinstance(instance.blob, dict)

    def test_bare_object_rejects_non_dict_values(self):
        """
        A JSON-encoded string (or any non-dict) for an object-typed argument
        fails validation instead of silently reaching the tool with the
        wrong type.  Bare Any used to pass these through.
        """
        model = self._convert({
            "properties": {"blob": {"type": "object"}},
            "required": ["blob"],
        })
        with pytest.raises(ValidationError):
            model.model_validate({"blob": '{"a": 1}'})
        with pytest.raises(ValidationError):
            model.model_validate({"blob": 42})

    def test_bare_object_optional_accepts_null_and_omission(self):
        """Non-required object args keep v1's tolerance of null/omission."""
        model = self._convert({
            "properties": {"blob": {"type": "object"}},
        })
        assert model.model_validate({}).blob is None
        assert model.model_validate({"blob": None}).blob is None

    def test_bare_object_json_schema_declares_object_type(self):
        """
        The provider-facing JSON schema for a bare object declares
        "type": "object" - the property that keeps provider adapters
        (notably langchain-google-genai's) from degrading it to STRING.
        """
        model = self._convert({
            "properties": {"blob": {"type": "object"}},
            "required": ["blob"],
        })
        blob_schema: Dict[str, Any] = model.model_json_schema()["properties"]["blob"]
        assert blob_schema.get("type") == "object"

    def test_object_with_properties_still_becomes_nested_model(self):
        """Objects that declare properties keep taking the nested-model path."""
        model = self._convert({
            "properties": {
                "opts": {
                    "type": "object",
                    "properties": {"depth": {"type": "int"}},
                    "required": ["depth"],
                },
            },
            "required": ["opts"],
        })
        instance = model.model_validate({"opts": {"depth": 3}})
        assert isinstance(instance.opts, BaseModel)
        assert instance.opts.depth == 3

    def test_array_of_bare_objects(self):
        """Bare objects inside array items get the same Dict treatment."""
        model = self._convert({
            "properties": {
                "records": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            "required": ["records"],
        })
        instance = model.model_validate({"records": [{"a": 1}, {"b": 2}]})
        assert instance.records == [{"a": 1}, {"b": 2}]
        with pytest.raises(ValidationError):
            model.model_validate({"records": ["not-a-dict"]})


class TestMalformedSpecHandling:
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
