
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

from neuro_san.internals.interfaces.agent_state_listener import AgentStateListener
from neuro_san.internals.interfaces.agent_storage_source import AgentStorageSource


class RecordingListener(AgentStateListener):
    """
    A test listener that records all state change notifications.
    """

    def __init__(self):
        self.added: List[str] = []
        self.modified: List[str] = []
        self.removed: List[str] = []

    def agent_added(self, agent_name: str, source: AgentStorageSource):
        self.added.append(agent_name)

    def agent_modified(self, agent_name: str, source: AgentStorageSource):
        self.modified.append(agent_name)

    def agent_removed(self, agent_name: str, source: AgentStorageSource):
        self.removed.append(agent_name)

    def reset(self):
        """
        Reset the state of the listener.
        """
        self.added.clear()
        self.modified.clear()
        self.removed.clear()
