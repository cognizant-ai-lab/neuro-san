
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
from typing import List
from typing import Tuple
from typing import Union
from typing import override

from logging import getLogger
from logging import Logger

from pathlib import Path

from watchdog.observers.polling import PollingObserver

from neuro_san.service.watcher.registries.registry_change_handler import RegistryChangeHandler
from neuro_san.service.watcher.registries.registry_observer import RegistryObserver


class PollingRegistryObserver(RegistryObserver):
    """
    Observer class for manifest file and its directory.
    """

    def __init__(self, manifest_path: Union[str, List[str]], poll_seconds: int):

        self.manifest_path: Union[str, List[str]] = manifest_path
        self.registry_observers: Dict[str, PollingObserver] = {}
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.poll_seconds: int = poll_seconds
        self.event_handler: RegistryChangeHandler = RegistryChangeHandler()

        split_manifest_paths: List[str] = manifest_path
        if isinstance(manifest_path, str):
            split_manifest_paths = manifest_path.split(" ")

        for split_component in split_manifest_paths:
            one_manifest_path: str = Path(split_component)
            registry_path: str = str(one_manifest_path.parent)
            if registry_path not in self.registry_observers:
                # One observer per unique registry path
                self.registry_observers[registry_path] = PollingObserver(timeout=self.poll_seconds)

    @override
    def start(self):
        """
        Start running observer
        """
        for registry_path, observer in self.registry_observers.items():
            observer.schedule(self.event_handler, path=registry_path, recursive=True)
            observer.start()
            self.logger.info("Registry polling watchdog started on: %s for manifest %s with polling every %d sec",
                             registry_path, self.manifest_path, self.poll_seconds)

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
