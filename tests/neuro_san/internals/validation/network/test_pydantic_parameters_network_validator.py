
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

from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.dictionary_validator import DictionaryValidator
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

    @staticmethod
    def _restore_fixture(filename: str) -> Dict[str, Any]:
        """
        Load a HOCON fixture from tests/fixtures/parameters_shape/.
        Runs through the same AgentNetworkRestorer filter chain
        (commondefs, defaults, name-correction) that production
        configs see, so test data mirrors real behaviour.
        """
        hocon_file: str = str(TestPydanticParametersNetworkValidator._FIXTURE_DIR / filename)
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
        the OpenAI {type, properties, required} shape.  The validator should
        not flag that as 'unknown keys'.
        """
        config: Dict[str, Any] = self._restore_fixture("flat_param_map.hocon")
        self.assertEqual(self.validator.validate(config), [])

    def test_agent_with_no_parameters_block_is_ignored(self):
        """Agents that don't declare a parameters block are not flagged."""
        config: Dict[str, Any] = self._restore_fixture("no_parameters.hocon")
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

    def test_unresolved_string_items_sanitized_before_pydantic(self):
        """
        When a commondef is missing, the string ``items`` reference stays
        unresolved after the restorer pipeline.  The sanitizer must replace
        it with a permissive dict before pydantic sees it, or from_dict()
        would crash.
        """
        config: Dict[str, Any] = self._restore_fixture(
            "unresolved_string_items.hocon",
        )
        self.assertEqual(self.validator.validate(config), [])
