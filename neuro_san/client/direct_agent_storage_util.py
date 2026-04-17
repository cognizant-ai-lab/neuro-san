
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
from typing import Dict

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage


class DirectAgentStorageUtil:
    """
    Sets up AgentNetworkStorage for direct usage.
    """

    @staticmethod
    def create_network_storage(manifest_networks: Dict[str, Dict[str, AgentNetwork]] = None,
                               storage_type: str = StorageClass.PUBLIC) -> AgentNetworkStorage:
        """
        Creates an AgentNetworkStorage instance for a given type.

        :param manifest_networks: Optional structure that is handed back from a RegistryManifestRestorer.restore()
                        call.  This has major keys being different network storage options like
                        "public" and "protected". The values are agent name -> AgentNetwork mappings.
                        By default the value is None, indicating we need to get this information
                        by calling the RegistryManifestRestorer.
        :param storage_type: The type of storage ("public" or "protected")
                        Default value is "public".
        :return: An AgentNetworkStorage populated from the Registry Manifest
        """
        network_storage = AgentNetworkStorage()

        if manifest_networks is None:
            manifest_restorer = RegistryManifestRestorer()
            manifest_networks = manifest_restorer.restore()

        storage_networks: Dict[str, AgentNetwork] = manifest_networks.get(storage_type)
        if storage_networks is None:
            return None

        for agent_name, agent_network in storage_networks.items():
            network_storage.add_agent_network(agent_name, agent_network)

        return network_storage
