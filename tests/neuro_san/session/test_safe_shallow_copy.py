
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

from unittest.mock import MagicMock

from neuro_san.session.session_invocation_context import SessionInvocationContext


class TestSafeShallowCopy:
    """
    Test cases for SessionInvocationContext.safe_shallow_copy(), which backs
    direct sessions to external agent networks on the same server.
    """

    def _make_context(self) -> SessionInvocationContext:
        pool = MagicMock()
        pool.get_executor.return_value = MagicMock()
        return SessionInvocationContext(
            agent_name="test_agent",
            async_session_factory=MagicMock(),
            async_executors_pool=pool,
            llm_factory=MagicMock(),
        )

    def test_clone_shares_request_reporting_and_origination(self):
        """
        The shallow copy intentionally shares request_reporting (so external
        agents' token accounting contributes to the request-wide totals) and
        origination (so instantiation indices stay consistent).
        """
        context = self._make_context()
        clone = context.safe_shallow_copy()

        assert clone.get_request_reporting() is context.get_request_reporting()
        assert clone.get_origination() is context.get_origination()

    def test_clone_gets_its_own_queue_and_journal(self):
        """Message routing state must NOT be shared with the clone."""
        context = self._make_context()
        clone = context.safe_shallow_copy()

        assert clone.get_queue() is not context.get_queue()
        assert clone.get_journal() is not context.get_journal()
        assert clone.get_work_done_event() is not context.get_work_done_event()

    def test_clone_is_cloned(self):
        """
        Only the clone reports being cloned.  LangChainTokenCounter.report()
        relies on this to let only the top-level front man (not front men of
        external networks invoked via direct sessions) emit the request-level
        token accounting message.
        """
        context = self._make_context()
        clone = context.safe_shallow_copy()

        assert clone.is_cloned() is True
        assert context.is_cloned() is False
