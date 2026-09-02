
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

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from langchain_core.messages.ai import AIMessage

from neuro_san.internals.journals.originating_journal import OriginatingJournal
from neuro_san.message.types.agent_message import AgentMessage


class TestOriginatingJournal:
    """
    Tests for OriginatingJournal's held-message dupe suppression.

    JournalingCallbackHandler.on_llm_end holds intermediate LLM output as a
    STRIPPED AGENT message via write_message_if_next_not_dupe, while the AI
    message that follows (from parse_chain_result) arrives unstripped. The
    dupe comparison must therefore ignore leading/trailing whitespace: with
    an exact comparison, a trailing newline in the final text is enough to
    send clients both the AGENT and AI copies of the same output.
    """

    ORIGIN = [{"tool": "front_man", "instantiation_index": 0}]

    def _make_journal(self):
        """Build a journal whose wrapped journal records written messages."""
        wrapped = MagicMock()
        wrapped.write_message = AsyncMock()
        journal = OriginatingJournal(wrapped_journal=wrapped, origin=self.ORIGIN)
        return journal, wrapped

    @pytest.mark.asyncio
    async def test_exact_dupe_is_suppressed(self):
        """
        A held AGENT message whose content matches the next message exactly
        is dropped: only the AI message reaches the wrapped journal.
        """
        journal, wrapped = self._make_journal()
        await journal.write_message_if_next_not_dupe(AgentMessage(content="the answer"))
        await journal.write_message(AIMessage(content="the answer"))

        written = [call.args[0] for call in wrapped.write_message.call_args_list]
        assert len(written) == 1
        assert written[0].content == "the answer"
        assert not isinstance(written[0], AgentMessage)

    @pytest.mark.asyncio
    async def test_dupe_comparison_ignores_edge_whitespace(self):
        """
        The held AGENT content is stripped at capture while the AI content is
        not, so the comparison must treat "the answer" and "the answer\\n" as
        the same content - otherwise clients receive both copies.
        """
        journal, wrapped = self._make_journal()
        await journal.write_message_if_next_not_dupe(AgentMessage(content="the answer"))
        await journal.write_message(AIMessage(content="the answer\n"))

        written = [call.args[0] for call in wrapped.write_message.call_args_list]
        assert len(written) == 1
        assert written[0].content == "the answer\n"

    @pytest.mark.asyncio
    async def test_different_content_flushes_pending_first(self):
        """
        A held AGENT message with genuinely different content is not a dupe:
        it is flushed ahead of the incoming message, preserving stream order.
        """
        journal, wrapped = self._make_journal()
        await journal.write_message_if_next_not_dupe(AgentMessage(content="a thought"))
        await journal.write_message(AIMessage(content="the answer"))

        written = [call.args[0] for call in wrapped.write_message.call_args_list]
        assert len(written) == 2
        assert isinstance(written[0], AgentMessage)
        assert written[0].content == "a thought"
        assert written[1].content == "the answer"
