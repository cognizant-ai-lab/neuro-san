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

import logging
import time
import threading
from typing import Dict

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.registries_watcher.periodic_updater.registry_event_observer import RegistryEventObserver
from neuro_san.service.registries_watcher.periodic_updater.registry_polling_observer import RegistryPollingObserver
from neuro_san.service.main_loop.server_status import ServerStatus


class ManifestPeriodicUpdater:
    """
    Class implementing periodic manifest directory updates
    by watching agent files and manifest file itself.
    """
    use_polling: bool = True

    def __init__(self,
                 network_storage: AgentNetworkStorage,
                 manifest_path: str,
                 update_period_seconds: int,
                 server_status: ServerStatus):
        """
        Constructor.

        :param network_storage: A AgentNetworkStorage instance which keeps all
                                the AgentNetwork instances.
        :param manifest_path: file path to server manifest file
        :param update_period_seconds: update period in seconds
        :param server_status: server status to register the state of updater
        """
        self.network_storage: AgentNetworkStorage = network_storage
        self.manifest_path: str = manifest_path
        self.update_period_seconds: int = update_period_seconds
        self.logger = logging.getLogger(self.__class__.__name__)
        self.updater = threading.Thread(target=self._run, daemon=True)
        if self.use_polling:
            poll_interval: int = self.compute_polling_interval(update_period_seconds)
            self.observer = RegistryPollingObserver(self.manifest_path, poll_interval)
        else:
            self.observer = RegistryEventObserver(self.manifest_path)
        self.server_status: ServerStatus = server_status
        self.go_run: bool = True

    def _run(self):
        """
        Function runs manifest file update cycle.
        """
        if self.update_period_seconds <= 0:
            # We should not run at all.
            return
        while self.go_run:
            self.server_status.set_updater_status(True)
            time.sleep(self.update_period_seconds)
            # Check events that may have been triggered in target registry:
            modified, added, deleted = self.observer.reset_event_counters()
            if modified == added == deleted == 0:
                # Nothing happened - go on observing
                continue
            # Some events were triggered - reload manifest file
            self.logger.info("Observed events: modified %d, added %d, deleted %d",
                             modified, added, deleted)
            self.logger.info("Updating manifest file: %s", self.manifest_path)
            agent_networks: Dict[str, AgentNetwork] = \
                RegistryManifestRestorer().restore(self.manifest_path)
            self.network_storage.setup_agent_networks(agent_networks)

    def compute_polling_interval(self, update_period_seconds: int) -> int:
        """
        Compute polling interval for polling observer
        given requested manifest update period
        """
        if update_period_seconds <= 5:
            return 1
        return int(round(update_period_seconds / 4))

    def start(self):
        """
        Start running periodic manifest updater.
        """
        self.logger.info("Starting manifest updater for %s with %d seconds period",
                         self.manifest_path, self.update_period_seconds)
        self.observer.start()
        self.updater.start()
