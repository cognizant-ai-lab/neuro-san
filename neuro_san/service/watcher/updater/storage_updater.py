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
from typing import List

import logging
import time
import threading

from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.main_loop.server_status import ServerStatus
from neuro_san.service.watcher.interfaces.startable import Startable
from neuro_san.service.watcher.registries.registry_storage_updater import RegistryStorageUpdater


# pylint: disable=too-many-instance-attributes
class StorageUpdater(Startable):
    """
    Class implementing periodic server updates
    by watching agent files and manifest file itself
    and other changes to AgentNetworkStorage instances.
    """
    def __init__(self,
                 network_storage_dict: Dict[str, AgentNetworkStorage],
                 manifest_path: str,
                 update_period_seconds: int,
                 server_status: ServerStatus):
        """
        Constructor.

        :param network_storage_dict: A dictionary of string (descripting scope) to
                    AgentNetworkStorage instance which keeps all the AgentNetwork instances
                    of a particular grouping.
        :param manifest_path: file path to server manifest file
        :param update_period_seconds: update period in seconds
        :param server_status: server status to register the state of updater
        """
        self.network_storage_dict: Dict[str, AgentNetworkStorage] = network_storage_dict
        self.manifest_path: str = manifest_path
        self.update_period_seconds: int = update_period_seconds
        self.logger = logging.getLogger(self.__class__.__name__)
        self.updater_thread = threading.Thread(target=self._run, daemon=True)

        poll_interval: int = self.compute_polling_interval(update_period_seconds)
        self.storage_updaters: List[StorageUpdater] = [
            RegistryStorageUpdater(network_storage_dict, manifest_path, poll_interval)
            # We will eventually have more here
        ]

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
            self.server_status.updater.set_status(True)
            time.sleep(self.update_period_seconds)
            for storage_updater in self.storage_updaters:
                storage_updater.update_storage()

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

        for storage_updater in self.storage_updaters:
            storage_updater.start()

        self.updater_thread.start()
