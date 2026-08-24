
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

from threading import Thread

import pytest

from pydantic import BaseModel
from pydantic import ValidationError

from neuro_san.internals.run_context.langchain.core.base_model_dictionary_converter \
    import BaseModelDictionaryConverter
from neuro_san.internals.run_context.langchain.core.tool_spec_error import ToolSpecError


# pylint: disable=too-many-public-methods
class TestBaseModelDictionaryConverter:
    """
    Test cases for the OpenAI-function-spec -> pydantic BaseModel conversion,
    the handling of malformed specs, and the spec-keyed model cache.

    Conversion: bare "object" parameters map to Dict[str, Any] rather than
    Any so that the JSON schema advertised to LLM providers declares a real
    object type.  A bare Any produced an empty schema ({}), which
    langchain-google-genai degrades to a STRING declaration - Gemini then
    sends JSON-encoded strings where tools expect dictionaries.

    Malformed specs: these produce clean ToolSpecErrors (or honor documented
    contracts) instead of raw AttributeError/TypeError crashes.  Explicit
    nulls and wrong-typed values are reachable from both hocon registries
    (pyhocon preserves explicit nulls) and the unvalidated JSON function
    specs external agents send over the network.

    The cache (issue #1209): specs are static registry data re-converted for
    every tool of every agent activation on every request, so from_dict()
    caches the created model class by spec content.  The cache tests pin
    down that contract: content-keyed sharing across converter instances,
    key-order sensitivity (field order flows through to the provider-facing
    JSON schema), LRU eviction, and the uncached fallbacks.
    """

    SPEC: Dict[str, Any] = {
        "properties": {
            "city": {"type": "string", "description": "Which city"},
            "days": {"type": "integer"},
        },
        "required": ["city"],
    }

    @pytest.fixture(autouse=True)
    def clear_model_cache(self):
        """
        The model cache is class-level, process-wide state.  Clear it around
        every test so tests stay order-independent.
        """
        BaseModelDictionaryConverter._model_cache.clear()   # pylint: disable=protected-access
        yield
        BaseModelDictionaryConverter._model_cache.clear()   # pylint: disable=protected-access

    def _convert(self, parameters: Dict[str, Any], name: str = "parameters") -> BaseModel:
        """
        Run the given parameters spec through a fresh converter.

        :param parameters: The parameters spec dictionary to convert
        :param name: The top-level field name for the converter
        :return: The pydantic model class from_dict() produces
        """
        converter = BaseModelDictionaryConverter(name)
        return converter.from_dict(parameters)

    # ---- Conversion of well-formed specs -----------------------------------

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

    # ---- Malformed specs ----------------------------------------------------

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

    # ---- The spec-keyed model cache (issue #1209) ---------------------------

    def test_equal_content_shares_model_across_instances(self):
        """
        The cache is keyed on content, not object identity, and is shared
        by all converter instances - this is what lets registry validation
        at load time warm the cache the tool-creation path reads from.
        """
        copy_of_spec: Dict[str, Any] = {
            "properties": {
                "city": {"type": "string", "description": "Which city"},
                "days": {"type": "integer"},
            },
            "required": ["city"],
        }
        first = self._convert(self.SPEC)
        second = self._convert(copy_of_spec)
        assert second is first

    def test_key_order_gets_separate_entries(self):
        """
        Field order flows through to the JSON schema advertised to LLM
        providers, so specs differing only in property order deliberately
        do NOT share a model.
        """
        reordered: Dict[str, Any] = {
            "properties": {
                "days": {"type": "integer"},
                "city": {"type": "string", "description": "Which city"},
            },
            "required": ["city"],
        }
        first = self._convert(self.SPEC)
        second = self._convert(reordered)
        assert second is not first
        assert list(first.model_fields.keys()) == ["city", "days"]
        assert list(second.model_fields.keys()) == ["days", "city"]

    def test_top_level_field_name_is_part_of_the_key(self):
        """
        The converter's top_level_field_name becomes the model's class name,
        which pydantic uses in validation error messages - same spec under a
        different name must not share a cache entry.
        """
        first = self._convert(self.SPEC, name="parameters")
        second = self._convert(self.SPEC, name="sly_data_schema")
        assert second is not first
        assert first.__name__ == "parameters"
        assert second.__name__ == "sly_data_schema"

    def test_lru_eviction_at_bound(self, monkeypatch):
        """
        Oldest entry falls out once the bound is exceeded; re-converting it
        afterwards builds a fresh class.
        """
        monkeypatch.setattr(BaseModelDictionaryConverter, "MODEL_CACHE_MAX_SIZE", 2)

        spec_a: Dict[str, Any] = {"properties": {"a": {"type": "string"}}}
        spec_b: Dict[str, Any] = {"properties": {"b": {"type": "string"}}}
        spec_c: Dict[str, Any] = {"properties": {"c": {"type": "string"}}}

        model_a = self._convert(spec_a)
        model_b = self._convert(spec_b)
        model_c = self._convert(spec_c)               # evicts spec_a

        assert self._convert(spec_c) is model_c       # still cached
        assert self._convert(spec_b) is model_b       # still cached
        assert self._convert(spec_a) is not model_a   # was evicted, rebuilt

    def test_unserializable_spec_builds_uncached(self):
        """
        A spec containing values JSON cannot represent (only reachable from
        in-process callers) still converts - it just never enters the cache.
        """
        spec: Dict[str, Any] = {
            "properties": {"blob": {"type": "string", "description": b"raw-bytes"}},
        }
        model = self._convert(spec)
        assert issubclass(model, BaseModel)
        assert len(BaseModelDictionaryConverter._model_cache) == 0   # pylint: disable=protected-access

    def test_deeply_nested_ignored_key_builds_uncached(self):
        """
        json.dumps walks the whole spec for keying and can exceed the
        recursion limit on deep nesting under a key the model builder
        itself never recurses into.  That RecursionError must fall back
        to an uncached build, not propagate out of from_dict.
        """
        deep: Dict[str, Any] = {}
        node: Dict[str, Any] = deep
        for _ in range(10000):
            node["next"] = {}
            node = node["next"]
        spec: Dict[str, Any] = {
            "properties": {"f": {"type": "string", "extra": deep}},
        }
        model = self._convert(spec)
        assert issubclass(model, BaseModel)
        assert model.model_validate({"f": "ok"}).f == "ok"
        assert len(BaseModelDictionaryConverter._model_cache) == 0   # pylint: disable=protected-access

    def test_bad_spec_raises_every_time_and_is_not_cached(self):
        """Spec errors propagate uncached so they are re-reported when re-seen."""
        bad_spec: Dict[str, Any] = {"properties": {"x": {"type": "interger"}}}
        for _ in range(2):
            with pytest.raises(ToolSpecError, match="Unrecognized type"):
                self._convert(bad_spec)
        assert len(BaseModelDictionaryConverter._model_cache) == 0   # pylint: disable=protected-access

    def test_concurrent_conversion_is_safe(self):
        """
        Threads racing on the same spec all get a usable model and the
        cache converges to one entry per distinct spec.
        """
        results: List[Any] = []

        def convert():
            results.append(self._convert(self.SPEC))

        threads: List[Thread] = [Thread(target=convert) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(results) == 8
        for model in results:
            assert issubclass(model, BaseModel)
            assert model.model_validate({"city": "Lisbon"}).city == "Lisbon"
        assert len(BaseModelDictionaryConverter._model_cache) == 1   # pylint: disable=protected-access

    def test_edited_spec_gets_fresh_model_not_stale_cache(self):
        """
        Hot-reload safety: the server can refresh registries every few
        seconds without a restart.  The cache is keyed on spec content, so
        an edited parameters block is a guaranteed miss - the old model
        cannot be served for it - while the unchanged case reuses a model
        identical to what a rebuild would produce.
        """
        before = self._convert(self.SPEC)

        edited_spec: Dict[str, Any] = {
            "properties": {
                "city": {"type": "string", "description": "Which city"},
                "days": {"type": "integer"},
                "units": {"type": "string"},   # field added by a hocon edit
            },
            "required": ["city"],
        }
        after = self._convert(edited_spec)

        assert after is not before
        assert "units" in after.model_fields
        assert "units" not in before.model_fields
