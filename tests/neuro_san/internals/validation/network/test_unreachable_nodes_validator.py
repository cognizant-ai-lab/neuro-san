
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
from neuro_san.internals.validation.network.unreachable_nodes_network_validator import UnreachableNodesNetworkValidator

from tests.neuro_san.internals.validation.network.abstract_network_validator_test import AbstractNetworkValidatorTest


class TestUnreachableNodesNetworkValidator(TestCase, AbstractNetworkValidatorTest):
    """
    Unit tests for UnreachableNodesNetworkValidator class.
    """

    def create_validator(self) -> DictionaryValidator:
        """
        Creates an instance of the validator
        """
        return UnreachableNodesNetworkValidator()

    def test_multiple_front_men(self):
        """
        Tests a network where there is > 1 front man.
        """
        validator: DictionaryValidator = self.create_validator()

        # Open a known good network file
        config: Dict[str, Any] = self.restore("hello_world.hocon")

        # Invalidate per the test - remove the link between the announcer and synonymizer
        config["tools"][0]["tools"] = []

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))

    def test_unreachable(self):
        """
        Tests a network where there is an unreachable agent.
        """
        validator: DictionaryValidator = self.create_validator()

        # Open a known good network file
        config: Dict[str, Any] = self.restore("esp_decision_assistant.hocon")

        # Invalidate per the test - remove the link between the prescriptor and the predictor
        config["tools"][1]["tools"] = []

        errors: List[str] = validator.validate(config)

        self.assertEqual(1, len(errors), errors[-1])

    def test_tools_as_string_does_not_crash(self):
        """
        Tests that the validator does not raise TypeError when an agent's `tools`
        field is a string instead of a list (issue #852). The shape error is
        reported by ToolsShapeValidator separately; this validator coerces
        the malformed value to empty and continues, so reachability checks
        produce a regular error rather than crashing.
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        # announcer's tools as a string instead of ["synonymizer"]
        config["tools"][0]["tools"] = "synonymizer"

        # Should not crash with TypeError.
        errors: List[str] = validator.validate(config)
        # With announcer's tools coerced to empty, no agent has down-chains,
        # so no front man can be identified.
        self.assertEqual(1, len(errors))
        self.assertIn("front man", errors[0].lower())

    def test_args_tools_dict_counts_as_down_chain(self):
        """
        Tests that agents referenced via `args.tools` (dict form, the coded
        tool convention) are recognized as down-chains for both front-man
        detection and reachability traversal.
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        # Replace announcer's traditional tools edge with a coded-tool style
        # args.tools dict edge.
        config["tools"][0]["tools"] = []
        config["tools"][0]["args"] = {"tools": {"helper": "synonymizer"}}

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors), errors)

    def test_args_tools_list_counts_as_down_chain(self):
        """
        Tests that agents referenced via `args.tools` (list form) are
        recognized as down-chains for both front-man detection and
        reachability traversal.
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        config["tools"][0]["tools"] = []
        config["tools"][0]["args"] = {"tools": ["synonymizer"]}

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors), errors)

    def test_args_tools_wrong_type_does_not_crash(self):
        """
        Tests that the validator does not crash when `args.tools` is neither
        a dict nor a list (e.g., a bare string). The malformed value is
        coerced to empty and traversal continues.
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        config["tools"][0]["tools"] = []
        config["tools"][0]["args"] = {"tools": "synonymizer"}

        # Should not crash with AttributeError on .values().
        errors: List[str] = validator.validate(config)
        # With both tools and args.tools coerced to empty, no agent has
        # down-chains.
        self.assertEqual(1, len(errors))
        self.assertIn("front man", errors[0].lower())
