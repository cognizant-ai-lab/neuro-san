
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
