
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

from neuro_san.internals.messages.agent_framework_message import AgentFrameworkMessage
from neuro_san.internals.run_context.langchain.core.run_context_runnable import RunContextRunnable


class TestRunContextRunnable:
    """Test cases for surfacing recoverable-error retries on the journal."""

    @pytest.mark.asyncio
    async def test_journal_retry_reason_writes_agent_framework_message(self):
        """
        journal_retry_reason should write a single AgentFrameworkMessage carrying the
        client-facing reason plus the error class name. AgentFrameworkMessage is the
        right type because it is excluded from chat history (no token bloat) and is
        written through this agent's journal (so it carries an origin and is never
        mistaken for the final answer).
        """
        written = []
        mock_journal = MagicMock()
        mock_journal.write_message = AsyncMock(side_effect=lambda msg, *_a, **_k: written.append(msg))

        runnable = RunContextRunnable.model_construct(journal=mock_journal)

        await runnable.journal_retry_reason(ValueError("bad json"), "the model's output could not be parsed")

        assert len(written) == 1
        message = written[0]
        assert isinstance(message, AgentFrameworkMessage)
        assert message.content == "Retrying: the model's output could not be parsed (ValueError)"

    @pytest.mark.asyncio
    async def test_invoke_agent_chain_surfaces_retry_reason_before_final_message(self):
        """
        When a recoverable error is retried until attempts are exhausted, each retry
        should emit an AgentFrameworkMessage diagnostic, and the final AIMessage must
        still come last so the journal stream order is preserved.
        """
        written = []
        mock_journal = MagicMock()
        mock_journal.write_message = AsyncMock(side_effect=lambda msg, *_a, **_k: written.append(msg))

        # A non-parse ValueError exercises the retry branch on every attempt.
        agent_chain = MagicMock()
        agent_chain.ainvoke = AsyncMock(side_effect=ValueError("not a parsing error"))

        # error_detector.handle_error is a pass-through for this test.
        error_detector = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=lambda output, _backtrace: output)

        runnable = RunContextRunnable.model_construct(
            journal=mock_journal,
            agent_chain=agent_chain,
            error_detector=error_detector,
            logger=MagicMock(),
        )

        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=2)

        # Two retries -> two diagnostics, then the final AIMessage.
        assert len(written) == 3
        assert all(isinstance(msg, AgentFrameworkMessage) for msg in written[:2])
        assert all(
            msg.content == "Retrying: the model's output could not be parsed (ValueError)"
            for msg in written[:2]
        )
        assert isinstance(written[-1], AIMessage)
