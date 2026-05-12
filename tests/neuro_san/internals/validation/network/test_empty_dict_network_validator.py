
# Copyright (C) 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
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

from unittest import TestCase

from neuro_san.internals.interfaces.dictionary_validator import DictionaryValidator
from neuro_san.internals.validation.network.empty_dict_network_validator import EmptyDictNetworkValidator

from tests.neuro_san.internals.validation.network.abstract_network_validator_test import AbstractNetworkValidatorTest


class TestEmptyDictNetworkValidator(TestCase, AbstractNetworkValidatorTest):
    """
    Unit tests for EmptyDictNetworkValidator class.
    """

    def create_validator(self) -> DictionaryValidator:
        """
        Creates an instance of the validator
        """
        return EmptyDictNetworkValidator()

    def test_empty_dict_in_llm_config(self):
        """
        Tests that an empty llm_config dictionary is detected
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        config["llm_config"] = {}

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))
        self.assertIn("llm_config", errors[0])

    def test_empty_dict_in_function(self):
        """
        Tests that an empty function dictionary on an agent is detected
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        config["tools"][0]["function"] = {}

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))
        self.assertIn("function", errors[0])

    def test_empty_dict_nested(self):
        """
        Tests that an empty dictionary nested deeply in the config is detected
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = {
            "llm_config": {
                "model_name": "gpt-4"
            },
            "tools": [
                {
                    "name": "test_agent",
                    "function": {
                        "description": "A test agent",
                        "parameters": {}
                    },
                    "instructions": "Do stuff",
                }
            ]
        }

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))
        self.assertIn("parameters", errors[0])

    def test_multiple_empty_dicts(self):
        """
        Tests that multiple empty dictionaries are all detected
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = {
            "llm_config": {},
            "tools": [
                {
                    "name": "test_agent",
                    "function": {},
                    "instructions": "Do stuff",
                }
            ]
        }

        errors: List[str] = validator.validate(config)
        self.assertEqual(2, len(errors))

    def test_no_empty_dicts(self):
        """
        Tests that a config with no empty dicts produces no errors
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = {
            "llm_config": {
                "model_name": "gpt-4"
            },
            "tools": [
                {
                    "name": "test_agent",
                    "function": {
                        "description": "A test agent"
                    },
                    "instructions": "Do stuff",
                }
            ]
        }

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors))

    def test_empty_dict_in_list(self):
        """
        Tests that an empty dictionary inside a list is detected
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = {
            "tools": [
                {}
            ]
        }

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))
        self.assertIn("tools[0]", errors[0])

    def test_error_message_contains_path(self):
        """
        Tests that error messages include the path to the empty dictionary
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = {
            "tools": [
                {
                    "name": "agent",
                    "allow": {
                        "connectivity": {}
                    },
                    "instructions": "Do stuff",
                }
            ]
        }

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))
        self.assertIn("tools[0].allow.connectivity", errors[0])
