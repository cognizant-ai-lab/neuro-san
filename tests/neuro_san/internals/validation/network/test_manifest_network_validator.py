
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

from neuro_san import REGISTRIES_DIR
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.validation.network.manifest_network_validator import ManifestNetworkValidator


class TestManifestNetworkValidator(TestCase):
    """
    Unit tests for ManifestNetworkValidator class.
    """

    @staticmethod
    def _restore_hello_world() -> Dict[str, Any]:
        """
        Loads the filtered hello_world registry network.

        :return: The network config dictionary
        """
        hocon_file: str = REGISTRIES_DIR.get_file_in_basis("hello_world.hocon")
        agent_network: AgentNetwork = AgentNetworkRestorer().restore(file_reference=hocon_file)
        return agent_network.get_config()

    def test_hello_world_has_no_errors(self) -> None:
        """
        The unchanged hello_world registry network passes the whole composite.
        """
        validator: ManifestNetworkValidator = ManifestNetworkValidator(network_name="hello_world")
        config: Dict[str, Any] = self._restore_hello_world()

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors), str(errors))

    def test_provider_tools_mistake_is_reported(self) -> None:
        """
        A malformed provider_tools surfaces through the composite, which is how the wiring of
        ProviderToolsNetworkValidator is observable without reaching into the composite's parts.
        """
        validator: ManifestNetworkValidator = ManifestNetworkValidator(network_name="hello_world")
        config: Dict[str, Any] = self._restore_hello_world()
        llm_config: Dict[str, Any] = config.get("llm_config")
        llm_config["provider_tools"] = "web_search"

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("network 'llm_config.provider_tools' must be a list, got str.", errors[0])
