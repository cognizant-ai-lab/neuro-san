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

from typing import Tuple
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import LLMResult

from neuro_san.internals.run_context.langchain.journaling.journaling_callback_handler import JournalingCallbackHandler


class TestExclusiveAgentAttribution:
    """An inherited handler must ignore events owned by a descendant agent."""

    @staticmethod
    def _make_handler() -> Tuple[JournalingCallbackHandler, MagicMock, MagicMock]:
        """
        Build a handler and mocks for observing its journal and origination calls.

        :return: The handler, mocked calling-agent journal, and mocked origination.
        """
        calling_agent_journal: MagicMock = MagicMock()
        calling_agent_journal.write_message = AsyncMock()
        calling_agent_journal.write_message_if_next_not_dupe = AsyncMock()
        origination: MagicMock = MagicMock()
        handler: JournalingCallbackHandler = JournalingCallbackHandler(
            calling_agent_journal=calling_agent_journal,
            base_journal=MagicMock(),
            parent_origin=[],
            origination=origination,
        )
        return handler, calling_agent_journal, origination

    @pytest.mark.asyncio
    async def test_descendant_llm_event_is_ignored(self) -> None:
        """An ancestor handler must not journal a descendant's LLM output."""
        ancestor, ancestor_journal, _ = self._make_handler()
        descendant, _, _ = self._make_handler()
        response = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="thinking"))]])

        with descendant.scope():
            await ancestor.on_llm_end(response)

        ancestor_journal.write_message_if_next_not_dupe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_descendant_tool_events_are_ignored_before_origin_allocation(self) -> None:
        """Descendant tool callbacks must be rejected before allocating an origin."""
        ancestor, ancestor_journal, ancestor_origination = self._make_handler()
        descendant, _, _ = self._make_handler()
        run_id = uuid4()

        with descendant.scope():
            await ancestor.on_tool_start(
                {"name": "search"}, "input", run_id=run_id,
                tags=["langchain_tool"], inputs={"query": "hello"}
            )
            await ancestor.on_tool_end("result", run_id=run_id, tags=["langchain_tool"])

        ancestor_journal.write_message.assert_not_awaited()
        ancestor_origination.add_spec_name_to_origin.assert_not_called()
        assert not ancestor._tool_journals  # pylint: disable=protected-access
        assert not ancestor._tool_origins  # pylint: disable=protected-access

    @pytest.mark.asyncio
    async def test_nearest_handler_processes_its_own_event(self) -> None:
        """The handler owning the nearest agent scope must process its event."""
        handler, journal, _ = self._make_handler()

        with handler.scope():
            await handler.on_tool_start({"name": "search"}, "input", run_id=uuid4(), tags=[], inputs={})

        journal.write_message.assert_awaited_once()
