
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

import warnings

from neuro_san.internals.run_context.langchain.core.base_model_dictionary_converter \
    import BaseModelDictionaryConverter
from neuro_san.internals.run_context.langchain.core.pydantic_argument_dictionary_converter \
    import PydanticArgumentDictionaryConverter


class TestPydanticArgumentDictionaryConverter:
    """
    Test cases for the flattening of pydantic model instances back into
    plain dictionaries before tool arguments are passed along.
    """

    def _make_instance(self, parameters, args):
        """Build a model via the same converter tool creation uses, then validate args."""
        model = BaseModelDictionaryConverter("parameters").from_dict(parameters)
        return model.model_validate(args)

    def test_nested_model_flattened_to_dict(self):
        """A nested object arg reaches the tool as a plain dict, not a model."""
        instance = self._make_instance(
            {
                "properties": {
                    "opts": {
                        "type": "object",
                        "properties": {"depth": {"type": "int"}},
                        "required": ["depth"],
                    },
                },
                "required": ["opts"],
            },
            {"opts": {"depth": 3}},
        )
        result = PydanticArgumentDictionaryConverter().to_dict(instance)
        assert result == {"opts": {"depth": 3}}
        assert isinstance(result["opts"], dict)

    def test_field_named_parse_obj_still_flattened(self):
        """
        Regression test for the duck-typed is_pydantic_object() check this
        replaced: a field literally named "parse_obj" (buildable under
        pydantic v2, which only warns about the shadowing) made
        getattr(value, "parse_obj") return the field's value, so
        callable() failed and the nested model escaped unflattened.
        isinstance(value, BaseModel) does not care about field names.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            instance = self._make_instance(
                {
                    "properties": {
                        "nested": {
                            "type": "object",
                            "properties": {"parse_obj": {"type": "string"}},
                            "required": ["parse_obj"],
                        },
                    },
                    "required": ["nested"],
                },
                {"nested": {"parse_obj": "hello"}},
            )
        result = PydanticArgumentDictionaryConverter().to_dict(instance)
        assert result == {"nested": {"parse_obj": "hello"}}
        assert isinstance(result["nested"], dict)

    def test_list_of_nested_models_flattened(self):
        """Models inside list values are flattened element by element."""
        instance = self._make_instance(
            {
                "properties": {
                    "hits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"url": {"type": "string"}},
                            "required": ["url"],
                        },
                    },
                },
                "required": ["hits"],
            },
            {"hits": [{"url": "a"}, {"url": "b"}]},
        )
        result = PydanticArgumentDictionaryConverter().to_dict(instance)
        assert result == {"hits": [{"url": "a"}, {"url": "b"}]}
        assert all(isinstance(hit, dict) for hit in result["hits"])

    def test_scalars_and_plain_values_pass_through(self):
        """Non-model values are returned unchanged."""
        instance = self._make_instance(
            {
                "properties": {
                    "query": {"type": "string"},
                    "count": {"type": "int"},
                    "blob": {"type": "object"},
                },
                "required": ["query"],
            },
            {"query": "q", "count": 2, "blob": {"free": "form"}},
        )
        result = PydanticArgumentDictionaryConverter().to_dict(instance)
        assert result == {"query": "q", "count": 2, "blob": {"free": "form"}}
