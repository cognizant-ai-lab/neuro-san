
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

from neuro_san.internals.interfaces.dictionary_validator import DictionaryValidator
from neuro_san.internals.validation.network.semantic_parameters_network_validator import \
    SemanticParametersNetworkValidator

from tests.neuro_san.internals.validation.network.abstract_network_validator_test import AbstractNetworkValidatorTest


class TestSemanticParametersNetworkValidator(TestCase, AbstractNetworkValidatorTest):
    """
    Unit tests for SemanticParametersNetworkValidator (Phase 2).

    Tests that the validator catches semantic issues pydantic is silent
    about: nested 'parameters' keys and undefined required references.
    """

    _FIXTURE_DIR: Path = Path(__file__).resolve().parents[4] / "fixtures" / "semantic_parameters"

    def setUp(self):
        self.validator = SemanticParametersNetworkValidator(
            network_name="test_network",
        )

    def create_validator(self) -> DictionaryValidator:
        """
        Creates an instance of the validator
        """
        return SemanticParametersNetworkValidator(
            network_name="test_network",
        )

    def test_clean_openai_shape_returns_no_errors(self):
        """A standard OpenAI-style parameters block passes."""
        config: Dict[str, Any] = self._restore_fixture("clean_openai_shape.hocon")
        self.assertEqual(self.validator.validate(config), [])

    def test_agent_with_no_parameters_block_is_ignored(self):
        """Agents that don't declare a parameters block are not flagged."""
        config: Dict[str, Any] = self._restore_fixture("no_parameters.hocon")
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

    def test_commondefs_items_bad_required(self):
        """
        An array whose items are defined via a commondefs string reference.
        After the filter chain resolves "items": "cao_item" into the actual
        schema dict, the semantic validator recurses into it and finds
        that required references an undefined property.
        """
        config: Dict[str, Any] = self._restore_fixture(
            "commondefs_items_bad_required.hocon",
        )
        errors = self.validator.validate(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("agent_d", errors[0])
        self.assertIn("parameters.properties.entries.items.required", errors[0])
        self.assertIn("undefined props", errors[0])

    def test_bad_parameters(self):
        """
        Tests a network where at least one of the tools has a malformed
        parameters block with a nested 'parameters' key.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self._restore_fixture("injected_nested_parameters.hocon")
        errors: List[str] = validator.validate(config)
        self.assertGreater(len(errors), 0)
