
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

import httpx
import pytest

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.outputs import LLMResult
from langchain_core.outputs.chat_generation import ChatGeneration
from openai import RateLimitError

from neuro_san.internals.run_context.langchain.journaling.journaling_callback_handler import JournalingCallbackHandler

from neuro_san.internals.run_context.langchain.core.run_context_runnable import RunContextRunnable
from neuro_san.message.types.agent_framework_message import AgentFrameworkMessage

from tests.neuro_san.message.content_fixtures import ContentFixtures


class TestParseChainResult:
    """
    Tests for the capture-side projection of list-form (block) content in
    parse_chain_result. The old inline flatten took only the first
    type=="text" block and skipped plain strings entirely, so multi-text
    responses lost everything past the first text block and list-of-str
    content became "".
    """

    @staticmethod
    def _make_runnable() -> RunContextRunnable:
        """Build a runnable whose error detector is a pass-through."""
        error_detector = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=lambda output: output)
        return RunContextRunnable.model_construct(error_detector=error_detector)

    def test_parse_chain_result_thinking_first_returns_answer(self):
        """
        An Anthropic thinking-first AIMessage projects to its answer text.
        """
        runnable = self._make_runnable()
        output = runnable.parse_chain_result(ContentFixtures.anthropic_thinking_first(), exception=None)
        assert output == "the answer"

    def test_parse_chain_result_concatenates_text_blocks(self):
        """
        Text blocks after the first must not be dropped: the old flatten
        stopped at the first type=="text" block and returned "part one, ".
        """
        runnable = self._make_runnable()
        message = AIMessage(content=[
            {"type": "text", "text": "part one, "},
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "part two"},
        ])
        assert runnable.parse_chain_result(message, exception=None) == "part one, part two"

    def test_parse_chain_result_list_of_str_returns_full_text(self):
        """
        List-of-strings content is legal per the pydantic annotation; the old
        flatten skipped non-dict items and returned "".
        """
        runnable = self._make_runnable()
        output = runnable.parse_chain_result(ContentFixtures.list_of_str(), exception=None)
        assert output == "part one, part two"

    def test_parse_chain_result_dict_messages_path_flattens_last_ai_message(self):
        """
        The normal chain result is a dict whose "messages" hold chat history;
        the last AIMessage found there gets the same full-text projection.
        """
        runnable = self._make_runnable()
        chain_result = {"messages": [
            HumanMessage(content="question"),
            ContentFixtures.anthropic_thinking_first(),
        ]}
        assert runnable.parse_chain_result(chain_result, exception=None) == "the answer"

    @pytest.mark.asyncio
    async def test_parse_chain_result_matches_on_llm_end_projection(self):
        """
        The dupe-leak regression: parse_chain_result and
        JournalingCallbackHandler.on_llm_end must project the same block
        content to the same text, because OriginatingJournal suppresses the
        held AGENT message only when the next AI message's content is equal.
        With the old divergent flattens this content pair differed and both
        messages reached clients.
        """
        message = AIMessage(content=[
            {"type": "text", "text": "part one, "},
            {"type": "text", "text": "part two"},
        ])

        runnable = self._make_runnable()
        parsed: str = runnable.parse_chain_result(message, exception=None)

        calling_agent_journal = MagicMock()
        calling_agent_journal.write_message_if_next_not_dupe = AsyncMock()
        handler = JournalingCallbackHandler(
            calling_agent_journal=calling_agent_journal,
            base_journal=MagicMock(),
            parent_origin=[],
            origination=MagicMock(),
        )
        await handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]))
        journaled = calling_agent_journal.write_message_if_next_not_dupe.call_args.args[0]

        assert parsed == journaled.content == "part one, part two"


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
        sensitive_logger = MagicMock()
        sensitive_logger.should_log = MagicMock(return_value=True)

        runnable = RunContextRunnable.model_construct(
            journal=mock_journal,
            sensitive_logger=sensitive_logger
        )

        await runnable.journal_retry_reason(ValueError("bad json"), "the model's output could not be parsed")

        assert len(written) == 1
        message = written[0]
        assert isinstance(message, AgentFrameworkMessage)
        assert message.content == "Retrying: the model's output could not be parsed (ValueError) - bad json"

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
        sensitive_logger = MagicMock()
        sensitive_logger.should_log = MagicMock(return_value=True)

        # A non-parse ValueError exercises the retry branch on every attempt.
        agent_chain = MagicMock()
        agent_chain.ainvoke = AsyncMock(side_effect=ValueError("not a parsing error"))

        # error_detector.handle_error is a pass-through for this test.
        error_detector = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=lambda output: output)

        runnable = RunContextRunnable.model_construct(
            journal=mock_journal,
            sensitive_logger=sensitive_logger,
            agent_chain=agent_chain,
            error_detector=error_detector,
            logger=MagicMock(),
        )

        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=2)

        # Two retries -> two diagnostics, then the final AIMessage.
        assert len(written) == 3
        for msg in written[:2]:
            assert isinstance(msg, AgentFrameworkMessage)
            assert msg.content == "Retrying: the model's output could not be parsed (ValueError) - not a parsing error"
        assert isinstance(written[-1], AIMessage)

    @pytest.mark.asyncio
    async def test_invoke_agent_chain_keeps_backtrace_out_of_client_output(self):
        """
        When the agent chain dies with an unhandled exception (e.g. an MCP tool
        transport error), the client-facing message must carry only the exception
        message: the full backtrace goes to the server log, not to the
        ErrorDetector as client-facing details.
        See https://github.com/cognizant-ai-lab/neuro-san/issues/1097
        """
        written = []
        mock_journal = MagicMock()
        mock_journal.write_message = AsyncMock(side_effect=lambda msg, *_a, **_k: written.append(msg))
        sensitive_logger = MagicMock()
        sensitive_logger.should_log = MagicMock(return_value=True)

        # A RuntimeError exercises the non-retryable broad-exception branch.
        agent_chain = MagicMock()
        agent_chain.ainvoke = AsyncMock(side_effect=RuntimeError("Server error '504 Gateway Time-out'"))

        # error_detector.handle_error is a pass-through for this test.
        error_detector = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=lambda output: output)

        runnable = RunContextRunnable.model_construct(
            journal=mock_journal,
            sensitive_logger=sensitive_logger,
            agent_chain=agent_chain,
            error_detector=error_detector,
            logger=MagicMock(),
        )

        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=3)

        # Unhandled exceptions are not retried: a single final AIMessage.
        assert len(written) == 1
        final = written[-1]
        assert isinstance(final, AIMessage)
        assert final.content == "Agent stopped due to exception Server error '504 Gateway Time-out'"
        # The ErrorDetector must not receive the backtrace as client-facing details.
        error_detector.handle_error.assert_called_once_with(
            "Agent stopped due to exception Server error '504 Gateway Time-out'")
        # The backtrace is logged server-side instead.
        assert any("Traceback" in str(call) for call in sensitive_logger.error.call_args_list)

    @pytest.mark.asyncio
    async def test_invoke_agent_chain_does_not_log_stale_backtrace(self):
        """
        A backtrace captured on an earlier attempt must not be logged when a
        later attempt fails via a branch that captures no backtrace: any logged
        traceback must correspond to the exception that ended the retry loop.
        Here attempt 1 fails with a KeyError (captures a backtrace) and
        attempt 2 fails with a rate-limit error (captures none), so no
        traceback should be logged at all.
        """
        written = []
        mock_journal = MagicMock()
        mock_journal.write_message = AsyncMock(side_effect=lambda msg, *_a, **_k: written.append(msg))
        sensitive_logger = MagicMock()
        sensitive_logger.should_log = MagicMock(return_value=True)

        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(429, request=request)
        rate_limit_error = RateLimitError("rate limited", response=response, body=None)

        agent_chain = MagicMock()
        agent_chain.ainvoke = AsyncMock(side_effect=[KeyError("missing field"), rate_limit_error])

        # error_detector.handle_error is a pass-through for this test.
        error_detector = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=lambda output: output)

        runnable = RunContextRunnable.model_construct(
            journal=mock_journal,
            sensitive_logger=sensitive_logger,
            agent_chain=agent_chain,
            error_detector=error_detector,
            logger=MagicMock(),
        )

        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=2)

        # The final message reflects the rate-limit failure from the last attempt...
        final = written[-1]
        assert isinstance(final, AIMessage)
        assert "rate limited" in final.content
        # ...so the stale KeyError traceback from attempt 1 must not be logged.
        assert not any("Traceback" in str(call) for call in sensitive_logger.error.call_args_list)
