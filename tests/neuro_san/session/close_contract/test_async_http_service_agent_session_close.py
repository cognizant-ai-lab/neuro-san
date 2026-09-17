
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
close()/is_closed() single-use contract tests for AsyncHttpServiceAgentSession.

These exercise the client-side contract only and never contact a server: the
closed-session guard raises before any network call, so no LLM key or running
service is required.
"""
from typing import Any
from typing import Dict

import pytest

from neuro_san.interfaces.async_agent_session import AsyncAgentSession
from neuro_san.session.agent_session_closed_error import AgentSessionClosedError
from neuro_san.session.async_http_service_agent_session import AsyncHttpServiceAgentSession


class TestAsyncHttpServiceAgentSessionClose:
    """An AsyncHttpServiceAgentSession is single-use once close() has been called."""

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

    def test_interface_default_is_closed_is_false(self):
        """The AsyncAgentSession base contract defaults is_closed() to False."""
        assert AsyncAgentSession().is_closed() is False
