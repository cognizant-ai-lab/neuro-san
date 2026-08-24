
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
from uuid import uuid4

import pytest

from langchain_core.messages.ai import AIMessage
from langchain_core.outputs import LLMResult
from langchain_core.outputs.chat_generation import ChatGeneration

from neuro_san.internals.run_context.langchain.journaling.journaling_callback_handler import JournalingCallbackHandler
from neuro_san.message.types.agent_message import AgentMessage

from tests.neuro_san.message.content_fixtures import ContentFixtures


class TestJournalingCallbackHandler:
    """
    Tests for JournalingCallbackHandler.

    on_llm_end journals the intermediate LLM output as an AGENT message using
    the shared full-text projection: block content yields all of its text,
    tool-call-only steps stay unjournaled, and stripping is preserved.

    on_tool_start should journal a diagnostic "Invoking" label even when the
    serialized tool carries no name.
    """

    @staticmethod
    def _make_handler():
        """Build a handler whose calling-agent journal records written messages."""
        calling_agent_journal = MagicMock()
        calling_agent_journal.write_message = AsyncMock()
        calling_agent_journal.write_message_if_next_not_dupe = AsyncMock()
        handler = JournalingCallbackHandler(
            calling_agent_journal=calling_agent_journal,
            base_journal=MagicMock(),
            parent_origin=[],
            origination=MagicMock(),
        )
        return handler, calling_agent_journal

    @staticmethod
    def _llm_result(message: AIMessage) -> LLMResult:
        """Wrap an AIMessage the way it arrives at on_llm_end."""
        return LLMResult(generations=[[ChatGeneration(message=message)]])

    @pytest.mark.asyncio
    async def test_on_llm_end_journals_full_text_of_block_content(self):
        """
        Thinking-first block content journals its answer text as an AGENT
        message, held for dupe comparison against the AI message that follows.
        """
        handler, journal = self._make_handler()
        await handler.on_llm_end(self._llm_result(ContentFixtures.anthropic_thinking_first()))
        message = journal.write_message_if_next_not_dupe.call_args.args[0]
        assert isinstance(message, AgentMessage)
        assert message.content == "the answer"

    @pytest.mark.asyncio
    async def test_on_llm_end_tool_call_only_step_stays_unjournaled(self):
        """
        A tool-call-only step has no text, so the journaling gate must keep
        skipping it - clients see the "Invoking:" message instead.
        """
        handler, journal = self._make_handler()
        tool_call_only = AIMessage(
            content=[{"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"query": "q"}}],
            tool_calls=[{"name": "lookup", "args": {"query": "q"}, "id": "toolu_1", "type": "tool_call"}],
        )
        await handler.on_llm_end(self._llm_result(tool_call_only))
        journal.write_message_if_next_not_dupe.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_llm_end_plain_string_content_still_journaled_stripped(self):
        """
        Plain-string content keeps its existing behavior: journaled stripped.
        """
        handler, journal = self._make_handler()
        await handler.on_llm_end(self._llm_result(AIMessage(content="  padded thought  ")))
        message = journal.write_message_if_next_not_dupe.call_args.args[0]
        assert message.content == "padded thought"

    @pytest.mark.asyncio
    async def test_on_tool_start_uses_tool_name_when_present(self):
        """A serialized tool with a name is reported verbatim."""
        handler, journal = self._make_handler()
        await handler.on_tool_start({"name": "search"}, "input", run_id=uuid4(), tags=[], inputs={})
        message = journal.write_message.call_args.args[0]
        assert isinstance(message, AgentMessage)
        assert message.content == "Invoking: `search` with:"
        assert message.structure["invoked_agent_name"] == "search"

    @pytest.mark.asyncio
    async def test_on_tool_start_falls_back_to_placeholder_when_name_missing(self):
        """A serialized tool with no name yields a diagnostic placeholder label
        instead of an empty "Invoking: ``"; the raw value is still reported."""
        handler, journal = self._make_handler()
        await handler.on_tool_start({}, "input", run_id=uuid4(), tags=[], inputs={})
        message = journal.write_message.call_args.args[0]
        assert message.content == "Invoking: `<unnamed tool>` with:"
        assert message.structure["invoked_agent_name"] is None
