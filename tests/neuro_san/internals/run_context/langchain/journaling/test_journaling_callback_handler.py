
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

from neuro_san.internals.run_context.langchain.journaling.journaling_callback_handler import JournalingCallbackHandler
from neuro_san.message.types.agent_message import AgentMessage


class TestOnToolStartInvokingLabel:
    """on_tool_start should journal a diagnostic "Invoking" label even when the
    serialized tool carries no name."""

    @staticmethod
    def _make_handler() -> Tuple[JournalingCallbackHandler, MagicMock]:
        """
        Build a handler whose calling-agent journal records written messages.

        :return: The handler and its mocked calling-agent journal.
        """
        calling_agent_journal: MagicMock = MagicMock()
        calling_agent_journal.write_message = AsyncMock()
        handler: JournalingCallbackHandler = JournalingCallbackHandler(
            calling_agent_journal=calling_agent_journal,
            base_journal=MagicMock(),
            parent_origin=[],
            origination=MagicMock(),
        )
        return handler, calling_agent_journal

    @pytest.mark.asyncio
    async def test_uses_tool_name_when_present(self) -> None:
        """A serialized tool with a name is reported verbatim."""
        handler, journal = self._make_handler()
        await handler.on_tool_start({"name": "search"}, "input", run_id=uuid4(), tags=[], inputs={})
        message = journal.write_message.call_args.args[0]
        assert isinstance(message, AgentMessage)
        assert message.content == "Invoking: `search` with:"
        assert message.structure["invoked_agent_name"] == "search"

    @pytest.mark.asyncio
    async def test_falls_back_to_placeholder_when_name_missing(self) -> None:
        """A serialized tool with no name yields a diagnostic placeholder label
        instead of an empty "Invoking: ``"; the raw value is still reported."""
        handler, journal = self._make_handler()
        await handler.on_tool_start({}, "input", run_id=uuid4(), tags=[], inputs={})
        message = journal.write_message.call_args.args[0]
        assert message.content == "Invoking: `<unnamed tool>` with:"
        assert message.structure["invoked_agent_name"] is None
