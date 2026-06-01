
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
from typing import List

from unittest import TestCase

from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.dictionary_validator import DictionaryValidator
from neuro_san.internals.validation.network.parameters_shape_network_validator import \
    ParametersShapeNetworkValidator

from tests.neuro_san.internals.validation.network.abstract_network_validator_test import AbstractNetworkValidatorTest


class TestParametersShapeNetworkValidator(TestCase, AbstractNetworkValidatorTest):
    """
    Unit tests for ParametersShapeNetworkValidator.

    Most test cases live in HOCON fixture files under
    tests/fixtures/parameters_shape/ so that test data is easy to read,
    comment, and extend without touching Python code.
    """

    _FIXTURE_DIR: Path = Path(__file__).resolve().parents[4] / "fixtures" / "parameters_shape"

    def setUp(self):
        self.validator = ParametersShapeNetworkValidator()

    def create_validator(self) -> DictionaryValidator:
        """
        Creates an instance of the validator
        """
        return ParametersShapeNetworkValidator()

    @staticmethod
    def _restore_fixture(filename: str) -> Dict[str, Any]:
        """
        Load a HOCON fixture from tests/fixtures/parameters_shape/.
        Runs through the same AgentNetworkRestorer filter chain
        (commondefs, defaults, name-correction) that production
        configs see, so test data mirrors real behaviour.
        """
        hocon_file: str = str(TestParametersShapeNetworkValidator._FIXTURE_DIR / filename)
        restorer = AgentNetworkRestorer()
        agent_network: AgentNetwork = restorer.restore(file_reference=hocon_file)
        config: Dict[str, Any] = agent_network.get_config()
        return config

    def test_clean_openai_shape_returns_no_errors(self):
        """A standard OpenAI-style parameters block passes."""
        config: Dict[str, Any] = self._restore_fixture("clean_openai_shape.hocon")
        self.assertEqual(self.validator.validate(config), [])

    def test_flat_param_map_shape_is_allowed(self):
        """
        Some agents use a flat 'parameters' map (param_name -> spec) instead of
        the OpenAI {type, properties, required} shape. The validator should
        not flag that as 'unknown keys'.
        """
        config: Dict[str, Any] = self._restore_fixture("flat_param_map.hocon")
        self.assertEqual(self.validator.validate(config), [])

    def test_agent_with_no_parameters_block_is_ignored(self):
        """Agents that don't declare a parameters block are not flagged."""
        config: Dict[str, Any] = self._restore_fixture("no_parameters.hocon")
        self.assertEqual(self.validator.validate(config), [])

    def test_zero_arg_function_type_object_without_properties_is_allowed(self):
        """
        Bare {type: 'object'} is a legitimate JSON-Schema / OpenAI shape for
        a function that takes no arguments. The validator must not flag it.
        """
        config: Dict[str, Any] = self._restore_fixture("zero_arg_function.hocon")
        self.assertEqual(self.validator.validate(config), [])

    def test_array_items_string_reference_is_skipped(self):
        """
        String references like "items": "cao_item" are not dicts and should
        be silently skipped (no false positives).
        """
        config: Dict[str, Any] = self._restore_fixture(
            "array_items_string_reference.hocon",
        )
        self.assertEqual(self.validator.validate(config), [])

    def test_valid_nested_object_and_array_passes(self):
        """
        A well-formed schema with nested objects and arrays passes cleanly.
        """
        config: Dict[str, Any] = self._restore_fixture(
            "valid_nested_object_and_array.hocon",
        )
        self.assertEqual(self.validator.validate(config), [])

    def test_nested_parameters_is_flagged(self):
        """The headline bug: 'parameters' key inside a parameters block."""
        config: Dict[str, Any] = self._restore_fixture("nested_parameters.hocon")
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("runner_tool", errors[0])
        self.assertIn("nested 'parameters'", errors[0])

    def test_required_references_undefined_property(self):
        """required listing keys that aren't in properties is flagged."""
        config: Dict[str, Any] = self._restore_fixture("bad_required.hocon")
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_a", errors[0])
        self.assertIn("undefined props", errors[0])
        self.assertIn("sample", errors[0])

    def test_nested_parameters_below_top_level_is_flagged(self):
        """
        A stray 'parameters' key inside a property's own schema (one level
        below the top) is caught.
        """
        config: Dict[str, Any] = self._restore_fixture(
            "nested_params_below_top_level.hocon",
        )
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("tool_a", errors[0])
        self.assertIn("parameters.properties.arg1", errors[0])
        self.assertIn("nested 'parameters'", errors[0])

    def test_nested_object_property_bad_required(self):
        """
        A nested object property whose required references an undefined
        property is flagged with a contextual path.
        """
        config: Dict[str, Any] = self._restore_fixture(
            "nested_object_bad_required.hocon",
        )
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_a", errors[0])
        self.assertIn("parameters.properties.address.required", errors[0])
        self.assertIn("undefined props", errors[0])
        self.assertIn("city", errors[0])

    def test_nested_object_property_bad_properties_type(self):
        """
        A nested object with properties that is not a dict is flagged
        by the pydantic conversion phase.
        """
        config: Dict[str, Any] = self._restore_fixture(
            "nested_object_bad_properties.hocon",
        )
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_b", errors[0])
        self.assertIn("pydantic model conversion failed", errors[0])

    def test_array_items_object_bad_required(self):
        """
        An array whose items schema is an object with bad required is flagged.
        """
        config: Dict[str, Any] = self._restore_fixture(
            "array_items_bad_required.hocon",
        )
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_c", errors[0])
        self.assertIn("parameters.properties.entries.items.required", errors[0])
        self.assertIn("undefined props", errors[0])

    def test_deeply_nested_object_error(self):
        """
        Errors three levels deep include the full dotted path.
        """
        config: Dict[str, Any] = self._restore_fixture("deeply_nested_error.hocon")
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("deep_tool", errors[0])
        self.assertIn(
            "parameters.properties.level1.properties.level2.required",
            errors[0],
        )

    def test_unrecognized_type_caught_by_pydantic(self):
        """
        A type string not in BaseModelDictionaryConverter.TYPE_LOOKUP is
        caught by the pydantic conversion phase.
        """
        config: Dict[str, Any] = self._restore_fixture("unrecognized_type.hocon")
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_e", errors[0])
        self.assertIn("pydantic model conversion failed", errors[0])

    def test_bad_parameters(self):
        """
        Tests a network where at least one of the tools has a malformed
        parameters block.
        """
        validator: DictionaryValidator = self.create_validator()

        # Open a known good network file
        config: Dict[str, Any] = self.restore("hello_world.hocon")

        # Invalidate per the test: inject a nested 'parameters' key
        tools: List = config.get("tools", [])
        first_tool: Dict[str, Any] = tools[0] if tools else {}
        first_tool["function"] = {
            "parameters": {
                "type": "object",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                },
            },
        }

        errors: List[str] = validator.validate(config)
        self.assertGreater(len(errors), 0)
