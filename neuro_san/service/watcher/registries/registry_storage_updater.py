
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
import time
from typing import Any
from typing import Dict

import datetime
from logging import getLogger
from logging import Logger

from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.watcher.interfaces.abstract_storage_updater import AbstractStorageUpdater
from neuro_san.service.watcher.registries.event_registry_observer import EventRegistryObserver
from neuro_san.service.watcher.registries.polling_registry_observer import PollingRegistryObserver
from neuro_san.service.watcher.registries.registry_observer import RegistryObserver


class RegistryStorageUpdater(AbstractStorageUpdater):
    """
    Implementation of the StorageUpdater interface that updates registries
    from changes in the file system.
    """

    use_polling: bool = True

    def __init__(self, network_storage_dict: Dict[str, AgentNetworkStorage],
                 watcher_config: Dict[str, Any]):
        """
        Constructor

        :param network_storage_dict: A dictionary of string (descripting scope) to
                    AgentNetworkStorage instance which keeps all the AgentNetwork instances
                    of a particular grouping.
        :param watcher_config: A config dict for StorageUpdaters
        """
        super().__init__(watcher_config.get("manifest_update_period_seconds"))

        self.logger: Logger = getLogger(self.__class__.__name__)
        self.network_storage_dict: Dict[str, AgentNetworkStorage] = network_storage_dict
        self.manifest_path: str = watcher_config.get("manifest_path")

        self.observer: RegistryObserver = None
        if self.use_polling:
            poll_interval: int = self.compute_polling_interval()
            self.observer = PollingRegistryObserver(self.manifest_path, poll_interval)
        else:
            self.observer = EventRegistryObserver(self.manifest_path)

    def compute_polling_interval(self) -> int:
        """
        :return: Polling interval for polling observer given requested manifest update period
        """
        update_period_seconds: int = self.get_update_period_in_seconds()
        if update_period_seconds <= 5:
            return 1
        return int(round(update_period_seconds / 4))

    def start(self):
        """
        Perform start up.
        """
        self.logger.info("Starting RegistryStorageUpdater for %s with %d seconds period",
                         self.manifest_path, self.update_period_in_seconds)
        self.observer.start()

    def log_next_update_time(self):
        """
        Log the time for next manifest file update check
        """
        # Log the NEXT update time
        next_time = time.time() + self.get_update_period_in_seconds()
        next_time_fmt: str = datetime.datetime.fromtimestamp(next_time).isoformat()
        self.logger.debug("Next time manifest will be checked for updates: %s", next_time_fmt)

    def update_storage(self):
        """
        Perform an update.
        Take a look at the file system observer and perform any updates
        to relevant AgentNetworkStorage from changes there.
        """
        # Check events that may have been triggered in target registry:
        modified, added, deleted = self.observer.reset_event_counters()

        if modified == added == deleted == 0:
            self.log_next_update_time()
            # Nothing happened - go on observing
            return

        # Some events were triggered - reload manifest file
        self.logger.info("Observed events: modified %d, added %d, deleted %d",
                         modified, added, deleted)
        self.logger.info("Updating manifest file: %s", self.manifest_path)

        agent_networks: Dict[str, Dict[str, AgentNetwork]] = RegistryManifestRestorer(self.manifest_path).restore()

        for storage_class in StorageClass.ALL_PERMANENT:
            storage: AgentNetworkStorage = self.network_storage_dict.get(storage_class)
            storage.setup_agent_networks(agent_networks.get(storage_class))

        self.log_next_update_time()
