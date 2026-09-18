
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
"""
See class comment for details.
"""
from typing import Any
from typing import Dict
from typing import Generator

from threading import Lock

from neuro_san.interfaces.agent_session import AgentSession


class CountingSession(AgentSession):
    """
    Minimal AgentSession stand-in for SessionCanceller unit tests.

    It implements only close(), recording how many times it was called in a
    thread-safe counter so tests can assert each registered session is closed
    exactly once -- even when register() and cancel() race on separate threads.
    The other AgentSession methods are never exercised by these tests and raise
    NotImplementedError if called.
    """

    def __init__(self):
        """
        Constructor.
        """
        self._lock: Lock = Lock()
        self._close_count: int = 0

    def close(self):
        """
        Record a close() call.
        """
        with self._lock:
            self._close_count += 1

    def get_close_count(self) -> int:
        """
        :return: The number of times close() has been called on this session.
        """
        with self._lock:
            return self._close_count

    def function(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Not used by these tests.
        """
        raise NotImplementedError

    def connectivity(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Not used by these tests.
        """
        raise NotImplementedError

    def streaming_chat(self, request_dict: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
        """
        Not used by these tests.
        """
        raise NotImplementedError
