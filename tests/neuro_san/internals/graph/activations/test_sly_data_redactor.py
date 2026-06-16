
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

from unittest import TestCase

from neuro_san.internals.graph.activations.sly_data_redactor import SlyDataRedactor


class TestSlyDataRedactor(TestCase):
    """
    Unit tests for SlyDataRedactor class.
    """

    def test_assumptions(self):
        """
        Can we construct?
        """
        agent_spec = None
        redactor = SlyDataRedactor(agent_spec)
        self.assertIsNotNone(redactor)

    def test_true_false(self):
        """
        Tests basic true/false operations of the SlyDataRedactor
        """
        agent_spec = {
            "allow": {
                "sly_data": {
                    "yes": True,
                    "no": False
                }
            }
        }
        redactor = SlyDataRedactor(agent_spec, config_keys=["allow.sly_data"])

        sly_data = {
            "yes": 1,
            "no": 0,
            "not_mentioned": -1,
        }

        redacted: Dict[str, Any] = redactor.filter_config(sly_data)

        self.assertIsNotNone(redacted.get("yes"))
        self.assertIsNone(redacted.get("no"))
        self.assertIsNone(redacted.get("not_mentioned"))

    def test_brute_force_true(self):
        """
        Tests the let-everything-through case of the SlyDataRedactor
        """
        agent_spec = {
            "allow": {
                "sly_data": True
            }
        }
        redactor = SlyDataRedactor(agent_spec, config_keys=["allow.sly_data"])

        sly_data = {
            "yes": 1,
            "no": 0,
            "not_mentioned": -1,
        }

        redacted: Dict[str, Any] = redactor.filter_config(sly_data)

        self.assertIsNotNone(redacted.get("yes"))
        self.assertIsNotNone(redacted.get("no"))
        self.assertIsNotNone(redacted.get("not_mentioned"))

    def test_brute_force_false(self):
        """
        Tests explicit let-nothing-through case of the SlyDataRedactor
        """
        agent_spec = {
            "allow": {
                "sly_data": False
            }
        }
        redactor = SlyDataRedactor(agent_spec, config_keys=["allow.sly_data"])

        sly_data = {
            "yes": 1,
            "no": 0,
            "not_mentioned": -1,
        }

        redacted: Dict[str, Any] = redactor.filter_config(sly_data)

        self.assertIsNone(redacted.get("yes"))
        self.assertIsNone(redacted.get("no"))
        self.assertIsNone(redacted.get("not_mentioned"))

    def test_no_spec(self):
        """
        Tests implicit let-nothing-through case of the SlyDataRedactor
        """
        agent_spec = {
        }
        redactor = SlyDataRedactor(agent_spec, config_keys=["allow.sly_data"])

        sly_data = {
            "yes": 1,
            "no": 0,
            "not_mentioned": -1,
        }

        redacted: Dict[str, Any] = redactor.filter_config(sly_data)

        self.assertIsNone(redacted.get("yes"))
        self.assertIsNone(redacted.get("no"))
        self.assertIsNone(redacted.get("not_mentioned"))

    def test_key_list(self):
        """
        Tests basic list specification where listed keys get through
        """
        agent_spec = {
            "allow": {
                "sly_data": ["yes"]
            }
        }
        redactor = SlyDataRedactor(agent_spec, config_keys=["allow.sly_data"])

        sly_data = {
            "yes": 1,
            "no": 0,
            "not_mentioned": -1,
        }

        redacted: Dict[str, Any] = redactor.filter_config(sly_data)

        self.assertIsNotNone(redacted.get("yes"))
        self.assertIsNone(redacted.get("no"))
        self.assertIsNone(redacted.get("not_mentioned"))

    def test_translation(self):
        """
        Tests translation of keys for the SlyDataRedactor
        """
        agent_spec = {
            "allow": {
                "sly_data": {
                    "yes": "affirmative",
                    "no": "negative"
                }
            }
        }
        redactor = SlyDataRedactor(agent_spec, config_keys=["allow.sly_data"])

        sly_data = {
            "yes": 1,
            "no": 0,
            "not_mentioned": -1,
        }

        redacted: Dict[str, Any] = redactor.filter_config(sly_data)

        self.assertIsNone(redacted.get("yes"))
        self.assertIsNone(redacted.get("no"))
        self.assertIsNone(redacted.get("not_mentioned"))
        self.assertIsNotNone(redacted.get("affirmative"))
        self.assertIsNotNone(redacted.get("negative"))
