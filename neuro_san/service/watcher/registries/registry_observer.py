
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

from neuro_san.internals.interfaces.startable import Startable


class RegistryObserver(Startable):
    """
    Interface for specific kinds of filesystem observing
    """

    def start(self):
        """
        Start running observer
        """
        raise NotImplementedError

    def reset_event_counters(self) -> Tuple[int, int, int]:
        """
        Reset event counters and return current counters.
        """
        raise NotImplementedError
