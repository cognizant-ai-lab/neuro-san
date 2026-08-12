
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

from leaf_common.validation.dictionary_validator import DictionaryValidator

from neuro_san.internals.validation.network.cycles_network_validator import CyclesNetworkValidator

from tests.neuro_san.internals.validation.network.abstract_network_validator_test import AbstractNetworkValidatorTest


class TestCyclesNetworkValidator(TestCase, AbstractNetworkValidatorTest):
    """
    Unit tests for CyclesNetworkValidator class.
    """

    def create_validator(self) -> DictionaryValidator:
        """
        Creates an instance of the validator
        """
        return CyclesNetworkValidator()

    def test_cycles(self):
        """
        Tests a network where there is a cycle.
        These can actually be ok, but we want to test that we can detect them.
        """
        validator: DictionaryValidator = self.create_validator()

        # Open a known good network file
        config: Dict[str, Any] = self.restore("esp_decision_assistant.hocon")

        # Invalidate per the test - add a link from the predictor to the prescriptor
        config["tools"][2]["tools"] = ["prescriptor"]

        errors: List[str] = validator.validate(config)

        self.assertEqual(1, len(errors), errors[-1])

    def test_tools_as_string_does_not_iterate_chars(self):
        """
        Tests that a malformed `tools` field (string instead of list) does
        not silently iterate the string character-by-character. coerce_tools
        treats it as empty; the shape error is reported separately by
        ToolsShapeValidator.
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("hello_world.hocon")
        # announcer's tools as a string instead of a list
        config["tools"][0]["tools"] = "synonymizer"

        errors: List[str] = validator.validate(config)
        # With char-iteration we'd traverse chars and possibly hit cycles by accident.
        # With defensive coercion, the cycle detection runs on empty down-chains
        # for this agent and finds no cycle.
        self.assertEqual(0, len(errors), errors)
