
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

import logging

from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.watcher.interfaces.storage_updater import StorageUpdater
from neuro_san.service.watcher.registries.event_registry_observer import EventRegistryObserver
from neuro_san.service.watcher.registries.polling_registry_observer import PollingRegistryObserver
from neuro_san.service.watcher.registries.registry_observer import RegistryObserver


class RegistryStorageUpdater(StorageUpdater):
    """
    Implementation of the StorageUpdater interface that updates registries
    from changes in the file system.
    """

    use_polling: bool = True

    def __init__(self, network_storage_dict: Dict[str, AgentNetworkStorage],
                 manifest_path: str,
                 poll_interval: int):
        """
        Constructor
        """

        self.logger = logging.getLogger(self.__class__.__name__)
        self.network_storage_dict: Dict[str, AgentNetworkStorage] = network_storage_dict
        self.manifest_path: str = manifest_path

        self.observer: RegistryObserver = None
        if self.use_polling:
            self.observer = PollingRegistryObserver(self.manifest_path, poll_interval)
        else:
            self.observer = EventRegistryObserver(self.manifest_path)

    def start(self):
        """
        Perform start up.
        """
        self.observer.start()

    def update_storage(self):
        """
        Perform an update.
        Take a look at the file system observer and perform any updates
        to relevant AgentNetworkStorage from changes there.
        """
        # Check events that may have been triggered in target registry:
        modified, added, deleted = self.observer.reset_event_counters()
        if modified == added == deleted == 0:
            # Nothing happened - go on observing
            return

        # Some events were triggered - reload manifest file
        self.logger.info("Observed events: modified %d, added %d, deleted %d",
                         modified, added, deleted)
        self.logger.info("Updating manifest file: %s", self.manifest_path)

        agent_networks: Dict[str, AgentNetwork] = RegistryManifestRestorer().restore(self.manifest_path)

        public_storage: AgentNetworkStorage = self.network_storage_dict.get("public")
        public_storage.setup_agent_networks(agent_networks)
