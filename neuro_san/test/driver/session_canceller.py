
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
from typing import List

from threading import Lock

from neuro_san.interfaces.agent_session import AgentSession


class SessionCanceller:
    """
    Thread-safe handle used to abort a single test's in-flight work from a
    different thread than the one running it.

    A test executes on a worker thread which creates one or more AgentSessions
    and drives their streaming_chat(). When the driver's main thread decides the
    test has timed out, it calls cancel() on that test's SessionCanceller, which closes
    every session registered so far. The service may detect the dropped connection on
    a subsequent result or heartbeat and terminate the server-side request; a silent
    stream may continue running until it produces output.

    There is one SessionCanceller per test (per future), but a test can open more
    than one session -- one per entry in its "connections" list -- so register()
    accumulates a list and cancel() closes them all. The list is also what makes
    the cancel-before-register race safe: a session registered after cancel() has
    fired is closed immediately (see register()) rather than lingering unclosed.
    """

    def __init__(self):
        """
        Constructor.
        """
        self._lock: Lock = Lock()
        self._sessions: List[AgentSession] = []
        self._cancelled: bool = False

    def register(self, session: AgentSession):
        """
        Register a session created by the worker thread so a later cancel() can
        close it. If cancel() already fired (a race where the timeout beat the
        session's creation), close this session immediately instead.

        :param session: The AgentSession to track for cancellation.
        """
        with self._lock:
            if not self._cancelled:
                self._sessions.append(session)
                return
        # Already cancelled before this session was registered: close it now so
        # its just-opened request does not linger on the server.
        session.close()

    def cancel(self):
        """
        Mark cancelled and close every registered session, dropping their
        connections. Safe to call once from the main thread.
        """
        with self._lock:
            self._cancelled = True
            sessions: List[AgentSession] = list(self._sessions)
        for session in sessions:
            session.close()
