
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
from typing import Any
from typing import Dict
from typing import List

from unittest import TestCase
from unittest.mock import patch

from leaf_common.validation.dictionary_validator import DictionaryValidator

from neuro_san.internals.validation.network.fully_qualified_class_network_validator import \
    FullyQualifiedClassNetworkValidator

from tests.neuro_san.internals.validation.network.abstract_network_validator_test import AbstractNetworkValidatorTest


class TestFullyQualifiedClassNetworkValidator(TestCase, AbstractNetworkValidatorTest):
    """
    Unit tests for FullyQualifiedClassNetworkValidator class.
    """

    # Index of the calculator agent in deep/math_guy.hocon
    CALCULATOR_INDEX: int = 1

    def create_validator(self) -> DictionaryValidator:
        """
        Creates an instance of the validator

        :return: The validator under test
        """
        return FullyQualifiedClassNetworkValidator()

    def validate_math_guy_class(self, class_ref: Any) -> List[str]:
        """
        Validates deep/math_guy.hocon with its calculator class reference replaced.

        :param class_ref: The value to use for the calculator's "class" key
        :return: The list of errors from the validator
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("deep/math_guy.hocon")
        config["tools"][self.CALCULATOR_INDEX]["class"] = class_ref
        errors: List[str] = validator.validate(config)
        return errors

    def test_relative_class_rejected(self):
        """
        Tests that the AGENT_TOOL_PATH-relative reference shipped in deep/math_guy.hocon is rejected
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("deep/math_guy.hocon")

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))
        self.assertIn("calculator.Calculator", errors[0])
        self.assertIn("'calculator' is not on the PYTHONPATH", errors[0])

    def test_fully_qualified_class_accepted(self):
        """
        Tests that a fully-qualified reference is accepted
        """
        errors: List[str] = self.validate_math_guy_class("neuro_san.coded_tools.math_guy.calculator.Calculator")
        self.assertEqual(0, len(errors), errors)

    def test_bare_class_name_rejected(self):
        """
        Tests that a class name without a module is rejected
        """
        errors: List[str] = self.validate_math_guy_class("Calculator")
        self.assertEqual(1, len(errors))
        self.assertIn("'<package>.<module>.<ClassName>'", errors[0])

    def test_relative_import_rejected(self):
        """
        Tests that a relative import name is rejected
        """
        errors: List[str] = self.validate_math_guy_class(".calculator.Calculator")
        self.assertEqual(1, len(errors))
        self.assertIn("'<package>.<module>.<ClassName>'", errors[0])

    def test_class_wrong_type(self):
        """
        Tests that a class reference that is not a string is rejected
        """
        errors: List[str] = self.validate_math_guy_class(123)
        self.assertEqual(1, len(errors))
        self.assertIn("must be a str", errors[0])

    def test_spec_less_module_is_findable(self):
        """
        Tests that a module find_spec() cannot locate because it lacks a __spec__ still counts as findable
        """
        with patch("neuro_san.internals.validation.network.fully_qualified_class_network_validator.find_spec",
                   side_effect=ValueError("no __spec__")):
            self.assertTrue(FullyQualifiedClassNetworkValidator.is_top_level_findable("some_package"))
