
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

from typing import Tuple
from typing import override

import logging

from pathlib import Path

from watchdog.observers import Observer

from neuro_san.service.watcher.registries.registry_change_handler import RegistryChangeHandler
from neuro_san.service.watcher.registries.registry_observer import RegistryObserver


class EventRegistryObserver(RegistryObserver):
    """
    Observer class for manifest file and its directory.
    """

    def __init__(self, manifest_path: str):
        # DEF - not doing multiple manifests yet cuz this path is not active.
        # See Polling version if we ever need to go there.
        self.manifest_path: str = str(Path(manifest_path).resolve())
        self.registry_path: str = str(Path(self.manifest_path).parent)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.observer: Observer = Observer()
        self.event_handler: RegistryChangeHandler = RegistryChangeHandler()

    @override
    def start(self):
        """
        Start running observer
        """
        self.observer.schedule(self.event_handler, path=self.registry_path, recursive=True)
        self.observer.start()
        self.logger.info("Registry watchdog started on: %s for manifest %s",
                         self.registry_path, self.manifest_path)

    @override
    def stop(self):
        """
        Perform steps to stop/shut-down
        By default this does nothing
        """

    def reset_event_counters(self) -> Tuple[int, int, int]:
        """
        Reset event counters and return current counters.
        """
        return self.event_handler.reset_event_counters()
