
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

from typing import Any
from typing import Dict

from threading import Event
from threading import Thread

import pytest

from neuro_san.session.agent_session_closed_error import AgentSessionClosedError
from neuro_san.session.http_service_agent_session import HttpServiceAgentSession


class TestHttpServiceAgentSession:
    """
    A HttpServiceAgentSession is single-use once close() has been called.

    These close()/is_closed() contract tests exercise the client-side contract only
    and never contact a server: the closed-session guard raises before any network
    call, so no LLM key or running service is required.

    test_close_aborts_streaming_read is the exception: a worker thread reads a live
    "drip" stream from a real in-process server (streaming_cancel_server fixture), and
    close() from the main thread must make the generator raise AgentSessionClosedError.
    It covers the data-flowing case only, since close() is best-effort for a read
    blocked on a fully silent stream (see HttpServiceAgentSession.close()).
    """

    @staticmethod
    def _make_session() -> HttpServiceAgentSession:
        """Build a session pointed at a nominal host/port (no connection is made)."""
        return HttpServiceAgentSession(host="127.0.0.1", port="8080", agent_name="unit_test_agent")

    def test_not_closed_initially(self):
        """A fresh session reports is_closed() False."""
        assert self._make_session().is_closed() is False

    def test_is_closed_after_close(self):
        """close() flips is_closed() to True."""
        session = self._make_session()
        session.close()
        assert session.is_closed() is True

    def test_close_is_idempotent(self):
        """close() can be called more than once without error."""
        session = self._make_session()
        session.close()
        session.close()
        assert session.is_closed() is True

    def test_function_raises_after_close(self):
        """function() on a closed session raises AgentSessionClosedError, not a connectivity ValueError."""
        session = self._make_session()
        session.close()
        with pytest.raises(AgentSessionClosedError):
            session.function({})

    def test_connectivity_raises_after_close(self):
        """connectivity() on a closed session raises AgentSessionClosedError."""
        session = self._make_session()
        session.close()
        with pytest.raises(AgentSessionClosedError):
            session.connectivity({})

    def test_streaming_chat_raises_after_close(self):
        """
        streaming_chat() on a closed session raises AgentSessionClosedError when
        iterated -- rather than yielding an empty stream that looks like the agent
        returned no messages.
        """
        session = self._make_session()
        session.close()
        request: Dict[str, Any] = {"user_message": {"type": "HUMAN", "text": "hi"}}
        with pytest.raises(AgentSessionClosedError):
            list(session.streaming_chat(request))

    # pylint: disable=redefined-outer-name
    def test_close_aborts_streaming_read(self, streaming_cancel_server):
        """
        With a live (data-flowing) stream being read, close() from another thread
        makes the streaming generator raise AgentSessionClosedError.
        """
        session = HttpServiceAgentSession(
            host="127.0.0.1", port=streaming_cancel_server.port, agent_name="drip")
        request: Dict[str, Any] = {"user_message": {"type": "HUMAN", "text": "go"}}

        got_first: Event = Event()
        result: Dict[str, Any] = {"error": None, "items": 0}

        def worker():
            try:
                for _ in session.streaming_chat(request):
                    result["items"] += 1
                    got_first.set()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                result["error"] = exc

        worker_thread: Thread = Thread(target=worker, name="post-header-client", daemon=True)
        worker_thread.start()

        # Deterministic: wait until the client is actively reading the stream, then
        # cancel from THIS thread.
        assert got_first.wait(timeout=5.0), "client never received the first streamed message"
        session.close()

        worker_thread.join(timeout=5.0)
        assert not worker_thread.is_alive(), "close() did not interrupt the streaming read"
        assert isinstance(result["error"], AgentSessionClosedError), \
            f"expected AgentSessionClosedError, got {result['error']!r}"
        assert result["items"] >= 1
