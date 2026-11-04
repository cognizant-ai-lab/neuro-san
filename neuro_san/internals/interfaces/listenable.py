
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
    Interface for objects that will notify Listeners when status changes on the implementation.
    Note that "Listener" here is typing for the generic and is undefined at this level.
    """

    @abstractmethod
    def add_listener(self, listener: Listener):
        """
        Add a listener to be notified when status of underlying object changes.

        :param listener: listener of type Listener to be added
        """
        raise NotImplementedError

    @abstractmethod
    def remove_listener(self, listener: Listener):
        """
        Remove a listener from registered set.

        :param listener: listener of type Listener to be removed
        """
        raise NotImplementedError

    @abstractmethod
    def get_listeners(self) -> List[Listener]:
        """
        :return: a list of listeners (of type Listener) that are listening.
        """
        raise NotImplementedError
