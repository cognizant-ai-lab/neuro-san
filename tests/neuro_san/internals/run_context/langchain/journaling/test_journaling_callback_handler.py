
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

import json

from typing import Any
from typing import List
from typing import Tuple

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from uuid import uuid4

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.tool import ToolMessage
from langchain_core.outputs import LLMResult
from langchain_core.outputs.chat_generation import ChatGeneration

from neuro_san.internals.run_context.langchain.journaling.journaling_callback_handler import JournalingCallbackHandler
from neuro_san.message.types.agent_message import AgentMessage
from neuro_san.message.types.agent_tool_result_message import AgentToolResultMessage
from neuro_san.message.utils.content_utils import ContentUtils

from tests.neuro_san.message.content_fixtures import ContentFixtures


class TestJournalingCallbackHandler(IsolatedAsyncioTestCase):
    """
    Tests for JournalingCallbackHandler.

    on_llm_end journals the intermediate LLM output as an AGENT message using
    the shared full-text projection: block content yields all of its text,
    tool-call-only steps stay unjournaled, and stripping is preserved.

    on_tool_start should journal a diagnostic "Invoking" label even when the
    serialized tool carries no name.

    on_tool_end preserves a tool's block-list output (text plus data blocks,
    as block-returning tools produce) as a JSON-safe list, and keeps the
    str() form for every other output shape.
    """

    @staticmethod
    def _make_handler() -> Tuple[JournalingCallbackHandler, MagicMock]:
        """
        Build a handler whose calling-agent journal records written messages.

        :return: The handler and its mocked calling-agent journal.
        """
        calling_agent_journal: MagicMock = MagicMock()
        calling_agent_journal.write_message = AsyncMock()
        calling_agent_journal.write_message_if_next_not_dupe = AsyncMock()
        handler: JournalingCallbackHandler = JournalingCallbackHandler(
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

    async def test_on_llm_end_journals_full_text_of_block_content(self) -> None:
        """
        Thinking-first block content journals its answer text as an AGENT
        message, held for dupe comparison against the AI message that follows.
        """
        handler, journal = self._make_handler()
        await handler.on_llm_end(self._llm_result(ContentFixtures.anthropic_thinking_first()))
        message = journal.write_message_if_next_not_dupe.call_args.args[0]
        assert isinstance(message, AgentMessage)
        assert message.content == "the answer"

    async def test_on_llm_end_tool_call_only_step_stays_unjournaled(self) -> None:
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

    async def test_on_llm_end_plain_string_content_still_journaled_stripped(self) -> None:
        """
        Plain-string content keeps its existing behavior: journaled stripped.
        """
        handler, journal = self._make_handler()
        await handler.on_llm_end(self._llm_result(AIMessage(content="  padded thought  ")))
        message = journal.write_message_if_next_not_dupe.call_args.args[0]
        assert message.content == "padded thought"

    async def test_on_tool_start_uses_tool_name_when_present(self) -> None:
        """A serialized tool with a name is reported verbatim."""
        handler, journal = self._make_handler()
        await handler.on_tool_start({"name": "search"}, "input", run_id=uuid4(), tags=[], inputs={})
        message = journal.write_message.call_args.args[0]
        assert isinstance(message, AgentMessage)
        assert message.content == "Invoking: `search` with:"
        assert message.structure["invoked_agent_name"] == "search"

    async def test_on_tool_start_falls_back_to_placeholder_when_name_missing(self) -> None:
        """A serialized tool with no name yields a diagnostic placeholder label
        instead of an empty "Invoking: ``"; the raw value is still reported."""
        handler, journal = self._make_handler()
        await handler.on_tool_start({}, "input", run_id=uuid4(), tags=[], inputs={})
        message = journal.write_message.call_args.args[0]
        assert message.content == "Invoking: `<unnamed tool>` with:"
        assert message.structure["invoked_agent_name"] is None

    @staticmethod
    async def _run_langchain_tool(output: Any) -> Tuple[AgentToolResultMessage, AgentMessage]:
        """
        Drive a langchain tool through on_tool_start and on_tool_end with the
        given output, the way langchain fires the callbacks.

        :param output: The tool output handed to on_tool_end
        :return: The AgentToolResultMessage written to the calling agent's journal
                 and the "Got result:" AgentMessage written to the tool's own journal
        """
        calling_agent_journal: MagicMock = MagicMock()
        calling_agent_journal.write_message = AsyncMock()
        base_journal: MagicMock = MagicMock()
        base_journal.write_message = AsyncMock()
        origination: MagicMock = MagicMock()
        origination.add_spec_name_to_origin = MagicMock(
            return_value=[{"tool": "mcp_tool", "instantiation_index": 0}])
        handler: JournalingCallbackHandler = JournalingCallbackHandler(
            calling_agent_journal=calling_agent_journal,
            base_journal=base_journal,
            parent_origin=[],
            origination=origination,
        )
        run_id = uuid4()
        tags: List[str] = ["langchain_tool"]
        await handler.on_tool_start({"name": "mcp_tool"}, "input", run_id=run_id, tags=tags, inputs={})
        await handler.on_tool_end(output, run_id=run_id, tags=tags)

        result: AgentToolResultMessage = calling_agent_journal.write_message.call_args_list[-1].args[0]
        got_result: AgentMessage = base_journal.write_message.call_args_list[-1].args[0]
        return result, got_result

    async def test_on_tool_end_str_output_unchanged(self) -> None:
        """
        Plain-string tool output is journaled exactly as before.
        """
        result, got_result = await self._run_langchain_tool("42")
        assert isinstance(result, AgentToolResultMessage)
        assert result.content == "42"
        assert got_result.structure["tool_output"] == "42"

    async def test_on_tool_end_preserves_block_list_output(self) -> None:
        """
        A ToolMessage carrying standard content blocks (text + image: the
        shape langchain-mcp-adapters>=0.2 produces, while the pinned <0.2
        adapter hands over text only) is journaled as that block list rather
        than the Python repr str() would have made of it.
        """
        blocks: List[Any] = ContentFixtures.mcp_tool_content()
        result, got_result = await self._run_langchain_tool(ToolMessage(content=blocks, tool_call_id="call_1"))
        assert result.content == blocks
        assert got_result.structure["tool_output"] == blocks

    async def test_on_tool_end_sanitizes_bytes_in_blocks(self) -> None:
        """
        Bytes payloads inside blocks become base64 strings in both the journaled
        message and the tool journal's structure, so both stay serializable.
        """
        blocks: List[Any] = [
            {"type": "text", "text": "chart"},
            {"type": "image", "base64": b"raw", "mime_type": "image/png"},
        ]
        result, got_result = await self._run_langchain_tool(blocks)
        assert result.content[1]["base64"] == "cmF3"
        json.dumps(result.content)
        json.dumps(got_result.structure)

    async def test_on_tool_end_non_block_list_keeps_str_form(self) -> None:
        """
        A list that is not standard content blocks (here list-of-str) keeps the
        str() form it has always been journaled with; the structure keeps the
        raw output as before.
        """
        result, got_result = await self._run_langchain_tool(["a", "b"])
        assert result.content == "['a', 'b']"
        assert got_result.structure["tool_output"] == ["a", "b"]

    async def test_on_tool_end_single_text_block_list_is_kept_as_blocks(self) -> None:
        """
        A tool returning a bare text-block list is journaled as that list, so
        its wire text becomes the text itself. This is a deliberate change
        from the Python repr such a list used to be journaled as.
        """
        blocks: List[Any] = [{"type": "text", "text": "42"}]
        result, got_result = await self._run_langchain_tool(blocks)
        assert result.content == blocks
        assert ContentUtils.flatten_to_text(result) == "42"
        assert got_result.structure["tool_output"] == blocks
