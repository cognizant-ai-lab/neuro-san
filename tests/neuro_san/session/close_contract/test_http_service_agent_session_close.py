
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
close()/is_closed() single-use contract tests for HttpServiceAgentSession.

These exercise the client-side contract only and never contact a server: the
closed-session guard raises before any network call, so no LLM key or running
service is required.
"""
from typing import Any
from typing import Dict

import pytest

from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.session.agent_session_closed_error import AgentSessionClosedError
from neuro_san.session.http_service_agent_session import HttpServiceAgentSession


class TestHttpServiceAgentSessionClose:
    """A HttpServiceAgentSession is single-use once close() has been called."""

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

    def test_interface_default_is_closed_is_false(self):
        """The AgentSession base contract defaults is_closed() to False (direct sessions can't be closed)."""
        assert AgentSession().is_closed() is False
