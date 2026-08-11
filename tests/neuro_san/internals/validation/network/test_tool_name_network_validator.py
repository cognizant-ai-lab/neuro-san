
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

from neuro_san.internals.validation.network.tool_name_network_validator import ToolNameNetworkValidator

from tests.neuro_san.internals.validation.network.abstract_network_validator_test import AbstractNetworkValidatorTest


class TestToolNameNetworkValidator(TestCase, AbstractNetworkValidatorTest):
    """
    Unit tests for ToolNameNetworkValidator class.
    """

    def create_validator(self) -> DictionaryValidator:
        """
        Creates an instance of the validator
        """
        return ToolNameNetworkValidator()

    def test_bad_name(self):
        """
        Tests a network where at least one of the nodes has a bad name
        """
        validator: DictionaryValidator = ToolNameNetworkValidator()

        # Open a known good network file
        config: Dict[str, Any] = self.restore("hello_world.hocon")

        # Invalidate per the test
        config["tools"][0]["name"] = "ann0un$er"

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors))

    def test_deep_name(self):
        """
        Tests a network where at least one of the nodes has a reference to
        an exeternal network in a directory hierachy.
        """
        validator: DictionaryValidator = ToolNameNetworkValidator()

        # Open a known good network file
        config: Dict[str, Any] = self.restore("deep/math_guy_passthrough.hocon")

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors))
