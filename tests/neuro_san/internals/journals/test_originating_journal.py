
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
from typing import List

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage

from neuro_san.internals.journals.originating_journal import OriginatingJournal
from neuro_san.message.types.agent_message import AgentMessage
from neuro_san.message.types.agent_tool_result_message import AgentToolResultMessage
from neuro_san.message.utils.content_utils import ContentUtils

from tests.neuro_san.message.content_fixtures import ContentFixtures


class TestOriginatingJournal(IsolatedAsyncioTestCase):
    """
    Tests for OriginatingJournal's held-message dupe suppression.

    JournalingCallbackHandler.on_llm_end holds intermediate LLM output as a
    STRIPPED AGENT message via write_message_if_next_not_dupe, while the AI
    message that follows (from parse_chain_result) arrives unstripped. The
    dupe comparison must therefore ignore leading/trailing whitespace: with
    an exact comparison, a trailing newline in the final text is enough to
    send clients both the AGENT and AI copies of the same output.

    The comparison also projects both sides to text: the held AGENT copy is
    always a flattened str, while the incoming AI message can carry block
    content (reasoning + text) once native messages are preserved. A raw
    equality between a str and a block list could never match, so without
    the projection every block-content answer would leak both copies.
    """

    ORIGIN = [{"tool": "front_man", "instantiation_index": 0}]

    def _make_journal(self):
        """Build a journal whose wrapped journal records written messages."""
        wrapped = MagicMock()
        wrapped.write_message = AsyncMock()
        journal = OriginatingJournal(wrapped_journal=wrapped, origin=self.ORIGIN)
        return journal, wrapped

    @staticmethod
    def _written_messages(wrapped: MagicMock) -> List[BaseMessage]:
        """
        Collect the messages that reached the wrapped journal.

        :param wrapped: The wrapped journal mock whose write_message calls to inspect
        :return: The messages written to the wrapped journal, in order
        """
        written: List[BaseMessage] = []
        for call in wrapped.write_message.call_args_list:
            written.append(call.args[0])
        return written

    async def test_exact_dupe_is_suppressed(self) -> None:
        """
        A held AGENT message whose content matches the next message exactly
        is dropped: only the AI message reaches the wrapped journal.
        """
        journal, wrapped = self._make_journal()
        await journal.write_message_if_next_not_dupe(AgentMessage(content="the answer"))
        await journal.write_message(AIMessage(content="the answer"))

        written: List[BaseMessage] = self._written_messages(wrapped)
        assert len(written) == 1
        assert written[0].content == "the answer"
        assert not isinstance(written[0], AgentMessage)

    async def test_dupe_comparison_ignores_edge_whitespace(self) -> None:
        """
        The held AGENT content is stripped at capture while the AI content is
        not, so the comparison must treat "the answer" and "the answer\\n" as
        the same content - otherwise clients receive both copies.
        """
        journal, wrapped = self._make_journal()
        await journal.write_message_if_next_not_dupe(AgentMessage(content="the answer"))
        await journal.write_message(AIMessage(content="the answer\n"))

        written: List[BaseMessage] = self._written_messages(wrapped)
        assert len(written) == 1
        assert written[0].content == "the answer\n"

    async def test_different_content_flushes_pending_first(self) -> None:
        """
        A held AGENT message with genuinely different content is not a dupe:
        it is flushed ahead of the incoming message, preserving stream order.
        """
        journal, wrapped = self._make_journal()
        await journal.write_message_if_next_not_dupe(AgentMessage(content="a thought"))
        await journal.write_message(AIMessage(content="the answer"))

        written: List[BaseMessage] = self._written_messages(wrapped)
        assert len(written) == 2
        assert isinstance(written[0], AgentMessage)
        assert written[0].content == "a thought"
        assert written[1].content == "the answer"

    async def test_block_content_dupe_is_suppressed(self) -> None:
        """
        The held AGENT copy is a flattened str while the incoming AI message
        carries reasoning + text blocks with the same visible text. Both sides
        are projected to text, so the AGENT copy is still recognized as a dupe
        and only the AI message reaches the wrapped journal.
        """
        journal, wrapped = self._make_journal()
        await journal.write_message_if_next_not_dupe(AgentMessage(content="the answer"))
        blocks: List[Dict[str, Any]] = [
            {"type": "reasoning", "reasoning": "hidden"},
            {"type": "text", "text": "the answer\n"},
        ]
        incoming: AIMessage = AIMessage(content=blocks)
        await journal.write_message(incoming)

        written: List[BaseMessage] = self._written_messages(wrapped)
        assert len(written) == 1
        assert written[0] is incoming

    async def test_block_content_with_different_text_flushes_pending(self) -> None:
        """
        Block content whose visible text differs from the held AGENT copy is
        not a dupe: the AGENT copy is flushed first, then the AI message.
        """
        journal, wrapped = self._make_journal()
        await journal.write_message_if_next_not_dupe(AgentMessage(content="a thought"))
        incoming: AIMessage = AIMessage(content=[{"type": "text", "text": "the answer"}])
        await journal.write_message(incoming)

        written: List[BaseMessage] = self._written_messages(wrapped)
        assert len(written) == 2
        assert isinstance(written[0], AgentMessage)
        assert written[0].content == "a thought"
        assert written[1] is incoming

    @pytest.mark.asyncio
    async def test_tool_result_history_copy_is_text_projected(self) -> None:
        """
        A tool result carrying text + image blocks is journaled with its blocks
        intact, but its chat-history copy is a plain AIMessage holding the
        history-safe text: providers reject data blocks in assistant-role
        history, and the image is replaced by a short reference.
        """
        wrapped: MagicMock = MagicMock()
        wrapped.write_message = AsyncMock()
        chat_history: List[BaseMessage] = []
        journal: OriginatingJournal = OriginatingJournal(wrapped_journal=wrapped, origin=self.ORIGIN,
                                                         chat_history=chat_history)
        blocks: List[Dict[str, Any]] = ContentFixtures.mcp_tool_content()
        tool_result: AgentToolResultMessage = AgentToolResultMessage(content=blocks, tool_result_origin=self.ORIGIN)
        await journal.write_message(tool_result)

        assert len(chat_history) == 1
        history_copy: BaseMessage = chat_history[0]
        assert isinstance(history_copy, AIMessage)
        assert not isinstance(history_copy, AgentToolResultMessage)
        assert history_copy.content == "Here is the chart.[image attachment: image/png]"

        written: List[BaseMessage] = self._written_messages(wrapped)
        assert written[0] is tool_result
        assert written[0].content == blocks

    @pytest.mark.asyncio
    async def test_tool_result_str_history_copy_unchanged(self) -> None:
        """
        A plain-string tool result keeps producing a plain AIMessage history
        copy with the identical text.
        """
        wrapped: MagicMock = MagicMock()
        wrapped.write_message = AsyncMock()
        chat_history: List[BaseMessage] = []
        journal: OriginatingJournal = OriginatingJournal(wrapped_journal=wrapped, origin=self.ORIGIN,
                                                         chat_history=chat_history)
        await journal.write_message(AgentToolResultMessage(content="tool says", tool_result_origin=self.ORIGIN))

        assert len(chat_history) == 1
        assert isinstance(chat_history[0], AIMessage)
        assert chat_history[0].content == "tool says"

    @pytest.mark.asyncio
    async def test_block_answer_history_copy_is_text_projected(self) -> None:
        """
        An AI answer carrying block content is journaled with its blocks intact,
        but its chat-history copy is a plain AIMessage holding only the text:
        the history is handed to whichever provider runs next (possibly a
        fallback from a different provider) and is exported as chat_context,
        and neither should carry provider-native blocks.
        """
        wrapped: MagicMock = MagicMock()
        wrapped.write_message = AsyncMock()
        chat_history: List[BaseMessage] = []
        journal: OriginatingJournal = OriginatingJournal(wrapped_journal=wrapped, origin=self.ORIGIN,
                                                         chat_history=chat_history)
        answer: BaseMessage = ContentUtils.normalize_message(ContentFixtures.anthropic_thinking_first())
        assert isinstance(answer.content, list)
        await journal.write_message(answer)

        assert len(chat_history) == 1
        history_copy: BaseMessage = chat_history[0]
        assert isinstance(history_copy, AIMessage)
        assert history_copy is not answer
        assert history_copy.content == "the answer"
        assert history_copy.response_metadata == {}

        written: List[BaseMessage] = self._written_messages(wrapped)
        assert written[0] is answer
        assert isinstance(written[0].content, list)

    @pytest.mark.asyncio
    async def test_str_answer_history_copy_is_same_instance(self) -> None:
        """
        A plain-string AI answer is appended to the chat history as the very
        same instance, exactly as before.
        """
        wrapped: MagicMock = MagicMock()
        wrapped.write_message = AsyncMock()
        chat_history: List[BaseMessage] = []
        journal: OriginatingJournal = OriginatingJournal(wrapped_journal=wrapped, origin=self.ORIGIN,
                                                         chat_history=chat_history)
        answer: AIMessage = AIMessage(content="the answer")
        await journal.write_message(answer)

        assert len(chat_history) == 1
        assert chat_history[0] is answer
