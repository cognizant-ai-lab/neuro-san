
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

from unittest import TestCase

from neuro_san.internals.interfaces.dictionary_validator import DictionaryValidator
from neuro_san.internals.validation.network.tools_shape_validator import ToolsShapeValidator

from tests.neuro_san.internals.validation.network.abstract_network_validator_test import AbstractNetworkValidatorTest


class TestToolsShapeValidator(TestCase, AbstractNetworkValidatorTest):
    """
    Unit tests for ToolsShapeValidator class.
    """

    def create_validator(self) -> DictionaryValidator:
        """
        Creates an instance of the validator
        """
        return ToolsShapeValidator()

    def test_tools_wrong_type(self):
        """
        Tests a network where tools is a string instead of a list
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        config["tools"][0]["tools"] = "synonymizer"

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))
        self.assertIn("must be a list", errors[0])

    def test_tools_invalid_element(self):
        """
        Tests a network where a tools list element is neither str nor dict
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        config["tools"][0]["tools"] = ["synonymizer", 123]

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))
        self.assertIn("must be a str or dict", errors[0])

    def test_tools_valid_with_dict_element(self):
        """
        Tests that a tools list with str and dict elements is valid
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        config["tools"][0]["tools"] = ["synonymizer", {"server": "mcp_server"}]

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors))

    def test_args_tools_dict_is_valid(self):
        """
        Tests that args.tools as a dict (the coded-tool convention) is valid.
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        config["tools"][0]["args"] = {"tools": {"helper": "synonymizer"}}

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors))

    def test_args_tools_list_is_valid(self):
        """
        Tests that args.tools as a list of agent names is valid.
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        config["tools"][0]["args"] = {"tools": ["synonymizer"]}

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors))

    def test_args_tools_wrong_type(self):
        """
        Tests a network where args.tools is neither a dict nor a list.
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        config["tools"][0]["args"] = {"tools": "synonymizer"}

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))
        self.assertIn("'args.tools' must be a dict or list", errors[0])

    def test_args_tools_missing_is_valid(self):
        """
        Tests that absence of args.tools is fine — it's optional.
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        # hello_world.hocon does not use args.tools anywhere; baseline should be clean.

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors))

    def test_coerce_tools_returns_list_as_is(self):
        """
        coerce_tools should return a well-formed tools list unchanged.
        """
        agent_spec: Dict[str, Any] = {"tools": ["a", "b"]}
        result: List[Any] = ToolsShapeValidator.coerce_tools(agent_spec, "agent_x")
        self.assertEqual(["a", "b"], result)

    def test_coerce_tools_coerces_string_to_empty(self):
        """
        coerce_tools should return an empty list when tools is a string,
        not iterate the string's characters.
        """
        agent_spec: Dict[str, Any] = {"tools": "synonymizer"}
        result: List[Any] = ToolsShapeValidator.coerce_tools(agent_spec, "agent_x")
        self.assertEqual([], result)

    def test_coerce_tools_missing_returns_empty(self):
        """
        coerce_tools should return an empty list when tools is missing.
        """
        agent_spec: Dict[str, Any] = {}
        result: List[Any] = ToolsShapeValidator.coerce_tools(agent_spec, "agent_x")
        self.assertEqual([], result)

    def test_coerce_args_tools_dict_returns_values(self):
        """
        coerce_args_tools should return dict.values() as a real list (not
        a dict_values view) when args.tools is a dict.
        """
        agent_spec: Dict[str, Any] = {"args": {"tools": {"a": "agent_a", "b": "agent_b"}}}
        result: List[Any] = ToolsShapeValidator.coerce_args_tools(agent_spec, "agent_x")
        self.assertIsInstance(result, list)
        self.assertEqual(sorted(result), ["agent_a", "agent_b"])

    def test_coerce_args_tools_list_returns_as_is(self):
        """
        coerce_args_tools should return the list directly when args.tools is a list.
        """
        agent_spec: Dict[str, Any] = {"args": {"tools": ["agent_a", "agent_b"]}}
        result: List[Any] = ToolsShapeValidator.coerce_args_tools(agent_spec, "agent_x")
        self.assertEqual(["agent_a", "agent_b"], result)

    def test_coerce_args_tools_wrong_type_returns_empty(self):
        """
        coerce_args_tools should return empty when args.tools is malformed
        (e.g., a bare string) — does not raise AttributeError on .values().
        """
        agent_spec: Dict[str, Any] = {"args": {"tools": "synonymizer"}}
        result: List[Any] = ToolsShapeValidator.coerce_args_tools(agent_spec, "agent_x")
        self.assertEqual([], result)

    def test_coerce_args_tools_missing_returns_empty(self):
        """
        coerce_args_tools should return empty when args.tools is absent.
        """
        agent_spec: Dict[str, Any] = {}
        result: List[Any] = ToolsShapeValidator.coerce_args_tools(agent_spec, "agent_x")
        self.assertEqual([], result)
