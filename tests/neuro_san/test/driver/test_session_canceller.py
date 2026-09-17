
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

from threading import Barrier
from threading import Thread

from neuro_san.test.driver.session_canceller import SessionCanceller

from tests.neuro_san.test.driver.counting_session import CountingSession


class TestSessionCanceller:
    """
    Deterministic unit tests for SessionCanceller's synchronization boundary.

    A missed close() would leave a timed-out request running on the server, so
    these cover the paths register()/cancel() implement: the normal
    register-then-cancel path with multiple sessions, the cancel-before-register
    race (both orderings), and the thread-safety invariant that every session is
    closed exactly once regardless of how register() and cancel() interleave.
    """

    def test_cancel_closes_all_registered_sessions(self):
        """
        Normal path: several sessions registered before cancel() are all closed
        exactly once (one canceller per test, one session per "connections" entry).
        """
        canceller: SessionCanceller = SessionCanceller()
        sessions: List[CountingSession] = [CountingSession() for _ in range(3)]
        for session in sessions:
            canceller.register(session)

        canceller.cancel()

        for session in sessions:
            assert session.get_close_count() == 1

    def test_register_after_cancel_closes_immediately(self):
        """
        Race path: a session registered after cancel() has already fired is closed
        immediately on registration rather than lingering unclosed.
        """
        canceller: SessionCanceller = SessionCanceller()
        canceller.cancel()

        session: CountingSession = CountingSession()
        canceller.register(session)

        assert session.get_close_count() == 1

    def test_mixed_ordering_closes_every_session_once(self):
        """
        Both orderings in one test: sessions registered before cancel() are closed
        by cancel(); a session registered after is closed on registration -- each
        exactly once.
        """
        canceller: SessionCanceller = SessionCanceller()
        before: List[CountingSession] = [CountingSession() for _ in range(2)]
        for session in before:
            canceller.register(session)

        canceller.cancel()

        after: CountingSession = CountingSession()
        canceller.register(after)

        for session in before + [after]:
            assert session.get_close_count() == 1

    def test_cancel_with_no_sessions_is_safe(self):
        """
        cancel() with nothing registered is a no-op and must not raise.
        """
        canceller: SessionCanceller = SessionCanceller()
        canceller.cancel()

    def test_cancel_is_idempotent(self):
        """
        cancel() called more than once (the driver may cancel on timeout and again
        on shutdown for a still-running test) closes each session only once.
        """
        canceller: SessionCanceller = SessionCanceller()
        session: CountingSession = CountingSession()
        canceller.register(session)

        canceller.cancel()
        canceller.cancel()

        assert session.get_close_count() == 1

    def test_concurrent_register_and_cancel_closes_each_once(self):
        """
        Thread-safety invariant: with many worker threads calling register() while
        the main thread calls cancel(), every session ends up closed exactly once.
        A session is either captured by cancel()'s snapshot or closed by its own
        post-cancel register() -- never both, never neither -- so the assertion is
        deterministic regardless of interleaving.
        """
        canceller: SessionCanceller = SessionCanceller()
        sessions: List[CountingSession] = [CountingSession() for _ in range(50)]
        # +1 party for the main thread, so all registers and the cancel are
        # released together to maximize interleaving.
        barrier: Barrier = Barrier(len(sessions) + 1)

        def register_after_barrier(session: CountingSession):
            barrier.wait()
            canceller.register(session)

        threads: List[Thread] = [
            Thread(target=register_after_barrier, args=(session,), daemon=True)
            for session in sessions
        ]
        for thread in threads:
            thread.start()

        barrier.wait()
        canceller.cancel()

        for thread in threads:
            thread.join(timeout=5.0)
            assert not thread.is_alive()

        for session in sessions:
            assert session.get_close_count() == 1
