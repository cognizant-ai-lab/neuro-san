
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
Transport-level test that HttpServiceAgentSession.close() aborts a streaming read
in the data-flowing post-header case.

Uses a real in-process server (streaming_cancel_server fixture) in "drip" mode:
it flushes headers + messages continuously, so a worker thread iterating
streaming_chat() is reading a live stream (response tracked). The main thread then
calls the synchronous close() and asserts the generator raises
AgentSessionClosedError (the cross-thread response-close path), rather than
surfacing a connectivity ValueError.

Note: this deliberately exercises the data-flowing case. The synchronous
`requests` client cannot reliably interrupt a read blocked on a fully SILENT
stream from another thread (see HttpServiceAgentSession.close()); close() is
therefore non-blocking (closes on a daemon thread) and best-effort for that case.
"""
from typing import Any
from typing import Dict

from threading import Event
from threading import Thread

from neuro_san.session.agent_session_closed_error import AgentSessionClosedError
from neuro_san.session.http_service_agent_session import HttpServiceAgentSession


class TestHttpServiceAgentSessionCloseIntegration:
    """close() interrupts a data-flowing post-header streaming read from another thread."""

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
