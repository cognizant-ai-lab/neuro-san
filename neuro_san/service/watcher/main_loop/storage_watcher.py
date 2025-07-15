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


from logging import getLogger
from logging import Logger
from math import gcd as greatest_common_divisor
from threading import Thread
from time import sleep
from time import time

from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.main_loop.server_status import ServerStatus
from neuro_san.service.watcher.interfaces.startable import Startable
from neuro_san.service.watcher.interfaces.storage_updater import StorageUpdater
from neuro_san.service.watcher.registries.registry_storage_updater import RegistryStorageUpdater


# pylint: disable=too-many-instance-attributes
class StorageWatcher(Startable):
    """
    Class implementing periodic server updates
    by watching agent files and manifest file itself
    and other changes to AgentNetworkStorage instances.
    """
    def __init__(self,
                 network_storage_dict: Dict[str, AgentNetworkStorage],
                 manifest_path: str,
                 update_period_in_seconds: int,
                 server_status: ServerStatus):
        """
        Constructor.

        :param network_storage_dict: A dictionary of string (descripting scope) to
                    AgentNetworkStorage instance which keeps all the AgentNetwork instances
                    of a particular grouping.
        :param manifest_path: file path to server manifest file
        :param update_period_in_seconds: update period in seconds
        :param server_status: server status to register the state of updater
        """
        self.network_storage_dict: Dict[str, AgentNetworkStorage] = network_storage_dict
        self.manifest_path: str = manifest_path
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.updater_thread = Thread(target=self._run, daemon=True)

        self.storage_updaters: List[StorageUpdater] = [
            RegistryStorageUpdater(network_storage_dict, update_period_in_seconds, manifest_path)
            # We will eventually have more here
        ]

        update_periods: List[int] = []
        for storage_updater in self.storage_updaters:
            update_period: int = storage_updater.get_update_period_in_seconds()
            if update_period > 0:
                # Anybody whose update period is 0 doesn't count.
                update_periods.append(update_period)

        # If we have nobody, then we shouldn't even run.
        # Luckily greatest_common_divisor() returns 0 for an empty list.
        self.update_period_in_seconds: int = greatest_common_divisor(*update_periods)

        self.server_status: ServerStatus = server_status
        self.keep_running: bool = True

    def _run(self):
        """
        Function runs manifest file update cycle.
        """
        if self.update_period_in_seconds <= 0:
            # We should not run at all.
            return

        while self.keep_running:
            self.server_status.updater.set_status(True)
            sleep(self.update_period_in_seconds)

            time_now_in_seconds: float = time()
            for storage_updater in self.storage_updaters:
                if storage_updater.needs_updating(time_now_in_seconds):
                    storage_updater.update_storage()

    def start(self):
        """
        Start running periodic manifest updater.
        """
        self.logger.info("Starting storage watcher for %s with %d seconds period",
                         self.manifest_path, self.update_period_in_seconds)

        for storage_updater in self.storage_updaters:
            storage_updater.start()

        self.updater_thread.start()
