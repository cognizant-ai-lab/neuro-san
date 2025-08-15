
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT
from typing import Dict

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage


class DirectAgentStorageUtil:
    """
    Sets up AgentNetworkStorage for direct usage.
    """

    @staticmethod
    def create_network_storage() -> AgentNetworkStorage:
        """
        :return: An AgentNetworkStorage populated from the Registry Manifest
        """
        network_storage = AgentNetworkStorage()
        manifest_restorer = RegistryManifestRestorer()
        manifest_networks: Dict[str, AgentNetwork] = manifest_restorer.restore()

        for agent_name, agent_network in manifest_networks.items():
            network_storage.add_agent_network(agent_name, agent_network)

        return network_storage
