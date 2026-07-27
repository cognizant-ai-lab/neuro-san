
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
from neuro_san.internals.validation.network.url_network_validator import UrlNetworkValidator

from tests.neuro_san.internals.validation.network.abstract_network_validator_test import AbstractNetworkValidatorTest


class TestUrlNetworkValidator(TestCase, AbstractNetworkValidatorTest):
    """
    Unit tests for UrlNetworkValidator class.
    """

    def create_validator(self) -> DictionaryValidator:
        """
        Creates an instance of the validator
        """
        return UrlNetworkValidator(external_agents=["/math_guy"])

    def test_valid(self, hocon_file: str = "hello_world.hocon"):
        """
        Tests a valid network
        """
        super().test_valid(hocon_file="math_guy_passthrough.hocon")

    def test_no_external_network(self):
        """
        Tests a network where at least one of the nodes does not have a listed external network
        """
        validator: DictionaryValidator = self.create_validator()

        # Open a known good network file
        config: Dict[str, Any] = self.restore("math_guy_passthrough.hocon")

        # Invalidate per the test
        config["tools"][0]["tools"][0] = "/invalid_network"

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))

    def test_tools_as_string_does_not_iterate_chars(self):
        """
        Tests that a malformed `tools` field (string instead of list) does
        not silently iterate the string character-by-character through
        check_safe_urls. coerce_tools treats it as empty; the shape error
        is reported separately by ToolsShapeValidator.
        """
        validator: DictionaryValidator = self.create_validator()

        config: Dict[str, Any] = self.restore("math_guy_passthrough.hocon")
        # Replace a list with a bare string URL.
        config["tools"][0]["tools"] = "/math_guy"

        errors: List[str] = validator.validate(config)
        # With char-iteration each char would be checked against the URL list.
        # With defensive coercion, the field is treated as empty and no URL
        # check runs for this agent.
        self.assertEqual(0, len(errors), errors)
