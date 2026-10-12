
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
from typing import Optional

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage

from neuro_san.internals.journals.journal import Journal
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
    content (reasoning + text). A raw equality between a str and a block list
    could never match, so without the projection every block-content answer
    would leak both copies.
    """

    ORIGIN: List[Dict[str, Any]] = [{"tool": "front_man", "instantiation_index": 0}]

    async def test_exact_dupe_is_suppressed(self) -> None:
        """
        A held AGENT message whose content matches the next message exactly
        is dropped: only the AI message reaches the wrapped journal.
        """
        wrapped: MagicMock = self._make_wrapped_journal()
        journal: OriginatingJournal = self._make_journal(wrapped)
        held: AgentMessage = AgentMessage(content="the answer")
        await journal.write_message_if_next_not_dupe(held)
        incoming: AIMessage = AIMessage(content="the answer")
        await journal.write_message(incoming)

        written: List[BaseMessage] = self._written_messages(wrapped)
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].content, "the answer")
        self.assertNotIsInstance(written[0], AgentMessage)

    async def test_dupe_comparison_ignores_edge_whitespace(self) -> None:
        """
        The held AGENT content is stripped at capture while the AI content is
        not, so the comparison treats "the answer" and "the answer\\n" as
        the same content and clients receive only the AI copy.
        """
        wrapped: MagicMock = self._make_wrapped_journal()
        journal: OriginatingJournal = self._make_journal(wrapped)
        held: AgentMessage = AgentMessage(content="the answer")
        await journal.write_message_if_next_not_dupe(held)
        incoming: AIMessage = AIMessage(content="the answer\n")
        await journal.write_message(incoming)

        written: List[BaseMessage] = self._written_messages(wrapped)
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].content, "the answer\n")

    async def test_different_content_flushes_pending_first(self) -> None:
        """
        A held AGENT message with genuinely different content is not a dupe:
        it is flushed ahead of the incoming message, preserving stream order.
        """
        wrapped: MagicMock = self._make_wrapped_journal()
        journal: OriginatingJournal = self._make_journal(wrapped)
        held: AgentMessage = AgentMessage(content="a thought")
        await journal.write_message_if_next_not_dupe(held)
        incoming: AIMessage = AIMessage(content="the answer")
        await journal.write_message(incoming)

        written: List[BaseMessage] = self._written_messages(wrapped)
        self.assertEqual(len(written), 2)
        self.assertIsInstance(written[0], AgentMessage)
        self.assertEqual(written[0].content, "a thought")
        self.assertEqual(written[1].content, "the answer")

    async def test_block_content_dupe_is_suppressed(self) -> None:
        """
        The held AGENT copy is a flattened str while the incoming AI message
        carries reasoning + text blocks with the same visible text. Both sides
        are projected to text, so the AGENT copy is still recognized as a dupe
        and only the AI message reaches the wrapped journal.
        """
        wrapped: MagicMock = self._make_wrapped_journal()
        journal: OriginatingJournal = self._make_journal(wrapped)
        held: AgentMessage = AgentMessage(content="the answer")
        await journal.write_message_if_next_not_dupe(held)
        blocks: List[Dict[str, Any]] = [
            {"type": "reasoning", "reasoning": "hidden"},
            {"type": "text", "text": "the answer\n"},
        ]
        incoming: AIMessage = AIMessage(content=blocks)
        await journal.write_message(incoming)

        written: List[BaseMessage] = self._written_messages(wrapped)
        self.assertEqual(len(written), 1)
        self.assertIs(written[0], incoming)

    async def test_block_content_with_different_text_flushes_pending(self) -> None:
        """
        Block content whose visible text differs from the held AGENT copy is
        not a dupe: the AGENT copy is flushed first, then the AI message.
        """
        wrapped: MagicMock = self._make_wrapped_journal()
        journal: OriginatingJournal = self._make_journal(wrapped)
        held: AgentMessage = AgentMessage(content="a thought")
        await journal.write_message_if_next_not_dupe(held)
        blocks: List[Dict[str, Any]] = [{"type": "text", "text": "the answer"}]
        incoming: AIMessage = AIMessage(content=blocks)
        await journal.write_message(incoming)

        written: List[BaseMessage] = self._written_messages(wrapped)
        self.assertEqual(len(written), 2)
        self.assertIsInstance(written[0], AgentMessage)
        self.assertEqual(written[0].content, "a thought")
        self.assertIs(written[1], incoming)

    async def test_tool_result_history_copy_is_text_projected(self) -> None:
        """
        A tool result carrying text + image blocks is journaled with its blocks
        intact, but its chat-history copy is a plain AIMessage holding the
        history-safe text: providers reject data blocks in assistant-role
        history, and the image is replaced by a short reference.
        """
        wrapped: MagicMock = self._make_wrapped_journal()
        chat_history: List[BaseMessage] = []
        journal: OriginatingJournal = self._make_journal(wrapped, chat_history)
        blocks: List[Dict[str, Any]] = ContentFixtures.mcp_tool_content()
        tool_result: AgentToolResultMessage = AgentToolResultMessage(content=blocks, tool_result_origin=self.ORIGIN)
        await journal.write_message(tool_result)

        self.assertEqual(len(chat_history), 1)
        history_copy: BaseMessage = chat_history[0]
        self.assertIsInstance(history_copy, AIMessage)
        self.assertNotIsInstance(history_copy, AgentToolResultMessage)
        self.assertEqual(history_copy.content, "Here is the chart.[image attachment: image/png]")

        written: List[BaseMessage] = self._written_messages(wrapped)
        self.assertIs(written[0], tool_result)
        self.assertEqual(written[0].content, blocks)

    async def test_tool_result_str_history_copy_unchanged(self) -> None:
        """
        A plain-string tool result gets a plain AIMessage history copy with
        the same text.
        """
        wrapped: MagicMock = self._make_wrapped_journal()
        chat_history: List[BaseMessage] = []
        journal: OriginatingJournal = self._make_journal(wrapped, chat_history)
        tool_result: AgentToolResultMessage = AgentToolResultMessage(content="tool says",
                                                                     tool_result_origin=self.ORIGIN)
        await journal.write_message(tool_result)

        self.assertEqual(len(chat_history), 1)
        self.assertIsInstance(chat_history[0], AIMessage)
        self.assertEqual(chat_history[0].content, "tool says")

    async def test_block_answer_history_copy_is_text_projected(self) -> None:
        """
        An AI answer carrying block content is journaled with its blocks intact,
        but its chat-history copy is a plain AIMessage holding only the text,
        with no response metadata: the history is handed to whichever provider
        runs next (possibly a fallback from a different provider) and is
        exported as chat_context, and neither should carry provider-native blocks.
        """
        wrapped: MagicMock = self._make_wrapped_journal()
        chat_history: List[BaseMessage] = []
        journal: OriginatingJournal = self._make_journal(wrapped, chat_history)
        provider_answer: AIMessage = ContentFixtures.anthropic_thinking_first()
        answer: BaseMessage = ContentUtils.normalize_message(provider_answer)
        self.assertIsInstance(answer.content, list)
        await journal.write_message(answer)

        self.assertEqual(len(chat_history), 1)
        history_copy: BaseMessage = chat_history[0]
        self.assertIsInstance(history_copy, AIMessage)
        self.assertIsNot(history_copy, answer)
        self.assertEqual(history_copy.content, "the answer")
        self.assertEqual(history_copy.response_metadata, {})

        written: List[BaseMessage] = self._written_messages(wrapped)
        self.assertIs(written[0], answer)
        self.assertIsInstance(written[0].content, list)

    async def test_str_answer_history_copy_is_same_instance(self) -> None:
        """
        A plain-string AI answer goes into the chat history as the same
        instance, not a copy.
        """
        wrapped: MagicMock = self._make_wrapped_journal()
        chat_history: List[BaseMessage] = []
        journal: OriginatingJournal = self._make_journal(wrapped, chat_history)
        answer: AIMessage = AIMessage(content="the answer")
        await journal.write_message(answer)

        self.assertEqual(len(chat_history), 1)
        self.assertIs(chat_history[0], answer)

    @staticmethod
    def _make_wrapped_journal() -> MagicMock:
        """
        Build the Journal mock that the OriginatingJournal under test wraps.

        :return: A Journal mock whose write_message records each written message
        """
        wrapped: MagicMock = MagicMock(spec=Journal)
        wrapped.write_message = AsyncMock()
        return wrapped

    def _make_journal(self, wrapped: MagicMock, chat_history: Optional[List[BaseMessage]] = None) -> OriginatingJournal:
        """
        Build the OriginatingJournal under test, with ORIGIN as its origin.

        :param wrapped: The Journal mock that the new journal writes to
        :param chat_history: The list that receives the chat-history copies, or None for no chat history
        :return: The OriginatingJournal that wraps the given mock
        """
        journal: OriginatingJournal = OriginatingJournal(wrapped_journal=wrapped, origin=self.ORIGIN,
                                                         chat_history=chat_history)
        return journal

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
