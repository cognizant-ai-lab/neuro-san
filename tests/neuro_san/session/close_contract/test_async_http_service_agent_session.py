
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

import asyncio

from threading import Event
from threading import Thread

import pytest

from neuro_san.session.agent_session_closed_error import AgentSessionClosedError
from neuro_san.session.async_http_service_agent_session import AsyncHttpServiceAgentSession


class TestAsyncHttpServiceAgentSession:
    """
    An AsyncHttpServiceAgentSession is single-use once close() has been called.

    These close()/is_closed() contract tests exercise the client-side contract only
    and never contact a server: the closed-session guard raises before any network
    call, so no LLM key or running service is required.

    The two test_close_aborts_* tests are the exception: they run the client on its
    own event loop in a background thread against a real in-process server
    (streaming_cancel_server fixture), and check that a synchronous close() from the
    main thread makes the request fail with AgentSessionClosedError, both before and
    after the response headers arrive.
    """

    @staticmethod
    def _make_session() -> AsyncHttpServiceAgentSession:
        """Build a session pointed at a nominal host/port (no connection is made)."""
        return AsyncHttpServiceAgentSession(host="127.0.0.1", port="8080", agent_name="unit_test_agent")

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

    @pytest.mark.asyncio
    async def test_function_raises_after_close(self):
        """function() on a closed session raises AgentSessionClosedError, not a connectivity ValueError."""
        session = self._make_session()
        session.close()
        with pytest.raises(AgentSessionClosedError):
            await session.function({})

    @pytest.mark.asyncio
    async def test_connectivity_raises_after_close(self):
        """connectivity() on a closed session raises AgentSessionClosedError."""
        session = self._make_session()
        session.close()
        with pytest.raises(AgentSessionClosedError):
            await session.connectivity({})

    @pytest.mark.asyncio
    async def test_streaming_chat_raises_after_close(self):
        """
        streaming_chat() on a closed session raises AgentSessionClosedError when
        iterated -- rather than yielding an empty stream that looks like the agent
        returned no messages.
        """
        session = self._make_session()
        session.close()
        request: Dict[str, Any] = {"user_message": {"type": "HUMAN", "text": "hi"}}
        with pytest.raises(AgentSessionClosedError):
            async for _ in session.streaming_chat(request):
                pass

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
