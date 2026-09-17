
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
Transport-level tests that AsyncHttpServiceAgentSession.close() -- called
synchronously from another thread -- aborts an in-flight request in both the
pre-header and post-header windows.

The client runs on its own event loop in a background thread while the main
thread calls the synchronous close(). This exercises the loop-scheduled aborts:
- post-header: close the tracked response (call_soon_threadsafe) to unblock an
  iter_chunked() read;
- pre-header: close the tracked ClientSession (run_coroutine_threadsafe) to abort
  a request still awaiting response headers (no total timeout).
Both must surface as AgentSessionClosedError.
"""
from typing import Any
from typing import Dict

import asyncio

from threading import Event
from threading import Thread

from neuro_san.session.agent_session_closed_error import AgentSessionClosedError
from neuro_san.session.async_http_service_agent_session import AsyncHttpServiceAgentSession


class TestAsyncHttpServiceAgentSessionCloseIntegration:
    """close() unblocks pre-header and post-header async requests from another thread."""

    @staticmethod
    def _run_client(session: AsyncHttpServiceAgentSession, request: Dict[str, Any],
                    got_first: Event, result: Dict[str, Any]):
        """Drive streaming_chat() to completion on a private event loop (own thread)."""
        async def drive():
            try:
                async for _ in session.streaming_chat(request):
                    result["items"] += 1
                    got_first.set()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                result["error"] = exc

        loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(drive())
        finally:
            # Drain any close()-scheduled tasks (e.g. session teardown) so the
            # loop shuts down cleanly without "task pending" warnings.
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    # pylint: disable=redefined-outer-name
    def test_close_aborts_blocked_post_header_read(self, streaming_cancel_server):
        """After headers arrive and the read blocks, close() raises AgentSessionClosedError."""
        session = AsyncHttpServiceAgentSession(
            host="127.0.0.1", port=streaming_cancel_server.port, agent_name="posthang")
        request: Dict[str, Any] = {"user_message": {"type": "HUMAN", "text": "go"}}

        got_first: Event = Event()
        result: Dict[str, Any] = {"error": None, "items": 0}
        client_thread: Thread = Thread(
            target=self._run_client, args=(session, request, got_first, result),
            name="async-post-header-client", daemon=True)
        client_thread.start()

        assert got_first.wait(timeout=5.0), "client never received the first streamed message"
        session.close()

        client_thread.join(timeout=5.0)
        assert not client_thread.is_alive(), "close() did not unblock the blocked read"
        assert isinstance(result["error"], AgentSessionClosedError), \
            f"expected AgentSessionClosedError, got {result['error']!r}"

    # pylint: disable=redefined-outer-name
    def test_close_aborts_pre_header_request(self, streaming_cancel_server):
        """
        While the request is still awaiting response headers, close() aborts it by
        closing the underlying ClientSession and raises AgentSessionClosedError.
        """
        session = AsyncHttpServiceAgentSession(
            host="127.0.0.1", port=streaming_cancel_server.port, agent_name="prehang")
        request: Dict[str, Any] = {"user_message": {"type": "HUMAN", "text": "go"}}

        result: Dict[str, Any] = {"error": None, "items": 0}
        client_thread: Thread = Thread(
            target=self._run_client, args=(session, request, Event(), result),
            name="async-pre-header-client", daemon=True)
        client_thread.start()

        # Deterministic: the server signals once it has received the request, at
        # which point the client is awaiting headers with no response yet.
        assert streaming_cancel_server.pre_request_received.wait(timeout=5.0), \
            "server never received the request"
        session.close()

        client_thread.join(timeout=5.0)
        assert not client_thread.is_alive(), "close() did not abort the pre-header request"
        assert isinstance(result["error"], AgentSessionClosedError), \
            f"expected AgentSessionClosedError, got {result['error']!r}"
        assert result["items"] == 0
