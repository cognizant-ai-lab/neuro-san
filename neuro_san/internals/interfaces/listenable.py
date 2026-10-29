
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

from typing import List

from abc import abstractmethod

from leaf_common.utils.interface import interface


@interface
class Listenable[Listener]:
    """
    Abstract interface for providing an AgentNetwork instance at run-time.
    Note that "Listener" here is typing for the generic and is undefined at this level.
    """

    @abstractmethod
    def add_listener(self, listener: Listener):
        """
        Add a listener to be notified when status of underlying object changes.
        """
        raise NotImplementedError

    @abstractmethod
    def remove_listener(self, listener: Listener):
        """
        Remove a listener from registered set.
        """
        raise NotImplementedError

    @abstractmethod
    def get_listeners(self) -> List[Listener]:
        """
        Return a list of listeners.
        """
        raise NotImplementedError
