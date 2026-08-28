
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

from pathlib import Path
from typing import Any
from typing import Dict

from unittest import TestCase

from leaf_common.validation.dictionary_validator import DictionaryValidator

from neuro_san.internals.validation.network.pydantic_parameters_network_validator import \
    PydanticParametersNetworkValidator

from tests.neuro_san.internals.validation.network.abstract_network_validator_test import AbstractNetworkValidatorTest


class TestPydanticParametersNetworkValidator(TestCase, AbstractNetworkValidatorTest):
    """
    Unit tests for PydanticParametersNetworkValidator (Phase 1).

    Tests that pydantic conversion catches type errors, malformed
    structures, and structural issues in parameters blocks.
    """

    _FIXTURE_DIR: Path = Path(__file__).resolve().parents[4] / "fixtures" / "pydantic_parameters"

    def setUp(self):
        self.validator = PydanticParametersNetworkValidator(
            network_name="test_network",
        )

    def create_validator(self) -> DictionaryValidator:
        """
        Creates an instance of the validator
        """
        return PydanticParametersNetworkValidator(
            network_name="test_network",
        )

    def test_clean_openai_shape_returns_no_errors(self):
        """A standard OpenAI-style parameters block passes."""
        config: Dict[str, Any] = self._restore_fixture("clean_openai_shape.hocon")
        self.assertEqual(self.validator.validate(config), [])

    def test_flat_param_map_shape_is_allowed(self):
        """
        Some agents use a flat 'parameters' map (param_name -> spec) instead of
        the OpenAI {type, properties, required} shape.  The validator should
        not flag that as 'unknown keys'.
        """
        config: Dict[str, Any] = self._restore_fixture("flat_param_map.hocon")
        self.assertEqual(self.validator.validate(config), [])

    def test_agent_with_no_parameters_block_is_ignored(self):
        """Agents that don't declare a parameters block are not flagged."""
        config: Dict[str, Any] = self._restore_fixture("no_parameters.hocon")
        self.assertEqual(self.validator.validate(config), [])

    def test_array_items_commondef_resolved_by_filter_chain(self):
        """
        String references like "items": "cao_item" are resolved to their
        actual schema dict by DictionaryCommonDefsConfigFilter during the
        restorer pipeline.  Pydantic sees the resolved dict and passes.
        """
        config: Dict[str, Any] = self._restore_fixture(
            "array_items_string_reference.hocon",
        )
        self.assertEqual(self.validator.validate(config), [])

    def test_nested_object_property_bad_properties_type(self):
        """
        A nested object with properties that is not a dict is flagged
        by the preflight validation.
        """
        config: Dict[str, Any] = self._restore_fixture(
            "nested_object_bad_properties.hocon",
        )
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_b", errors[0])
        self.assertIn("properties must be an object", errors[0])

    def test_unrecognized_type_caught_by_preflight(self):
        """
        A type string not in BaseModelDictionaryConverter.TYPE_LOOKUP is
        caught by the pre-flight validation with a clear message.
        """
        config: Dict[str, Any] = self._restore_fixture("unrecognized_type.hocon")
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_e", errors[0])
        self.assertIn("unrecognized type", errors[0])
        self.assertIn("integer", errors[0])

    def test_array_missing_items_caught_by_preflight(self):
        """An array property without 'items' is caught with a clear message."""
        config: Dict[str, Any] = self._restore_fixture("array_missing_items.hocon")
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_f", errors[0])
        self.assertIn("missing 'items'", errors[0])

    def test_null_property_value_caught_by_preflight(self):
        """A null property value is caught with a clear message."""
        config: Dict[str, Any] = self._restore_fixture("null_property_value.hocon")
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_g", errors[0])
        self.assertIn("is null", errors[0])

    def test_non_dict_property_caught_by_preflight(self):
        """A property whose value is a scalar instead of a dict is caught."""
        config: Dict[str, Any] = self._restore_fixture("non_dict_property.hocon")
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_h", errors[0])
        self.assertIn("must be an object", errors[0])

    def test_missing_type_key_caught_by_preflight(self):
        """A property schema without a 'type' key is caught."""
        config: Dict[str, Any] = self._restore_fixture("missing_type_key.hocon")
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_i", errors[0])
        self.assertIn("missing 'type'", errors[0])

    def test_non_dict_items_caught_by_preflight(self):
        """An array whose 'items' is not a dict is caught."""
        config: Dict[str, Any] = self._restore_fixture("non_dict_items.hocon")
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_j", errors[0])
        self.assertIn("items must be", errors[0])

    def test_nested_array_missing_items_caught_by_preflight(self):
        """An array-of-arrays where the inner array lacks 'items' is caught."""
        config: Dict[str, Any] = self._restore_fixture(
            "nested_array_missing_items.hocon",
        )
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_k", errors[0])
        self.assertIn("missing 'items'", errors[0])

    def test_non_string_type_caught_by_preflight(self):
        """A 'type' value that is not a string (e.g. a list) is caught."""
        config: Dict[str, Any] = self._restore_fixture("non_string_type.hocon")
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_h", errors[0])
        self.assertIn("'type' must be a string", errors[0])

    def test_json_schema_type_aliases_are_accepted(self):
        """
        Standard JSON Schema / OpenAI function spec type names
        ("integer", "number", "bool") are accepted via TYPE_LOOKUP aliases,
        both as scalar property types and inside array "items".
        """
        config: Dict[str, Any] = self._restore_fixture(
            "json_schema_type_aliases.hocon",
        )
        self.assertEqual(self.validator.validate(config), [])

    def test_invalid_pydantic_field_names_caught(self):
        """
        Parameter names that pydantic v2 cannot accept as field names
        ("model_config", leading underscores) are rejected with a clear
        error instead of pydantic's cryptic TypeError/NameError.
        """
        config: Dict[str, Any] = self._restore_fixture(
            "invalid_param_names.hocon",
        )
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 2)
        self.assertIn("agent_f", errors[0])
        self.assertIn("model_config", errors[0])
        self.assertIn("agent_g", errors[1])
        self.assertIn("_private", errors[1])
        for error in errors:
            self.assertIn("pydantic model conversion failed", error)

    def test_string_items_commondef_resolved_before_pydantic(self):
        """
        String ``items`` commondef references are resolved to their actual
        schema dict by the restorer filter chain before validation.  Pydantic
        sees the resolved dict and from_dict() succeeds.
        """
        config: Dict[str, Any] = self._restore_fixture(
            "unresolved_string_items.hocon",
        )
        self.assertEqual(self.validator.validate(config), [])
