
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

from neuro_san.internals.graph.persistence.periodic_manifest_dict_config_filter import PeriodicManifestDictConfigFilter


class TestPeriodicManifestDictConfigFilter(TestCase):
    """
    Unit tests for PeriodicManifestDictConfigFilter class.
    """

    def test_assumptions(self):
        """
        Tests when the allow block is not present anywhere
        """
        config_filter = PeriodicManifestDictConfigFilter("manifest.hocon", "agent_network")
        self.assertIsNotNone(config_filter)

    def test_no_value(self):
        """
        Tests when the "periodic" key does not exist
        """
        config_filter = PeriodicManifestDictConfigFilter("manifest.hocon", "agent_network")

        basis_config: Dict[str, Any] = {}
        filtered_config: Dict[str, Any] = config_filter.filter_config(basis_config)
        self.assertIsNotNone(filtered_config)

        periodic: bool = filtered_config.get("periodic")
        self.assertIsNotNone(periodic)
        self.assertFalse(periodic)

    def test_false(self):
        """
        Tests when the "periodic" key is false
        """
        config_filter = PeriodicManifestDictConfigFilter("manifest.hocon", "agent_network")

        basis_config: Dict[str, Any] = {
            "periodic": False
        }
        filtered_config: Dict[str, Any] = config_filter.filter_config(basis_config)
        self.assertIsNotNone(filtered_config)

        periodic: bool = filtered_config.get("periodic")
        self.assertIsNotNone(periodic)
        self.assertFalse(periodic)

    def test_true(self):
        """
        Tests when the "periodic" key is false
        """
        config_filter = PeriodicManifestDictConfigFilter("manifest.hocon", "agent_network")

        basis_config: Dict[str, Any] = {
            "periodic": True
        }
        filtered_config: Dict[str, Any] = config_filter.filter_config(basis_config)
        self.assertIsNotNone(filtered_config)

        periodic: Dict[str, Any] = filtered_config.get("periodic")
        self.assertIsNotNone(periodic)

        # None is OK. Default is True.
        enabled: bool = periodic.get("enable")
        self.assertIsNone(enabled)

        interactions: List[Dict[str, Any]] = periodic.get("interactions")
        self.assertIsNotNone(interactions)
        self.assertEqual(1, len(interactions))
