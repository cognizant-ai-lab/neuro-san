
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

from functools import partial

from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import httpx

from langchain_core.agents import AgentFinish
from langchain_core.messages.ai import AIMessage
from langchain_core.messages.ai import AIMessageChunk
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.outputs import LLMResult
from langchain_core.outputs.chat_generation import ChatGeneration
from openai import RateLimitError

from neuro_san.internals.run_context.langchain.journaling.journaling_callback_handler import JournalingCallbackHandler

from neuro_san.internals.run_context.langchain.core.run_context_runnable import RunContextRunnable
from neuro_san.message.types.agent_framework_message import AgentFrameworkMessage
from neuro_san.message.utils.content_utils import ContentUtils

from tests.neuro_san.message.content_fixtures import ContentFixtures


# One test module per class is the repo convention, and RunContextRunnable
# has many independent branches to pin, so the test count exceeds pylint's
# default of 20 public methods.
class TestRunContextRunnable(IsolatedAsyncioTestCase):  # pylint: disable=too-many-public-methods
    """
    Tests for RunContextRunnable: the capture-side projection of list-form
    (block) content in parse_chain_result, and the surfacing of
    recoverable-error retries on the journal.

    The old inline flatten in parse_chain_result took only the first
    type=="text" block and skipped plain strings entirely, so multi-text
    responses lost everything past the first text block and list-of-str
    content became "".

    find_ai_message is the single place that locates the provider-native
    AIMessage inside a chain result (dict, AgentFinish or bare AIMessage);
    parse_chain_result keeps its exact behavior on top of it.

    invoke_agent_chain journals the provider-native answer (normalized to
    standard blocks) when it carries block content, and keeps the plain
    text-only AIMessage shape for everything else.
    """

    @staticmethod
    def _passthrough(output: str) -> str:
        """
        Return the given output unchanged, standing in for ErrorDetector.handle_error
        in tests that do not exercise error rewriting.

        :param output: The chain output text handed to the error detector
        :return: The same output, untouched
        """
        return output

    @staticmethod
    def _record(written: List[BaseMessage], message: BaseMessage, *_args: Any, **_kwargs: Any) -> None:
        """
        Append the given message to the written list, standing in for Journal.write_message
        so tests can inspect everything the runnable journaled.

        :param written: The list that collects every journaled message, in order
        :param message: The message being journaled
        :param _args: Further positional arguments write_message accepts (its origin); ignored
        :param _kwargs: Further keyword arguments write_message accepts; ignored
        """
        written.append(message)

    @staticmethod
    def _logged_traceback(sensitive_logger: MagicMock) -> bool:
        """
        Tell whether any error() call on the given logger mock carried a traceback.

        :param sensitive_logger: The mocked sensitive logger whose error() calls are inspected
        :return: True if the arguments of any error() call mention "Traceback", False otherwise
        """
        for call in sensitive_logger.error.call_args_list:
            if "Traceback" in str(call):
                return True
        return False

    @staticmethod
    def _make_runnable() -> RunContextRunnable:
        """Build a runnable whose error detector is a pass-through."""
        error_detector = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=TestRunContextRunnable._passthrough)
        return RunContextRunnable.model_construct(error_detector=error_detector)

    def test_parse_chain_result_thinking_first_returns_answer(self):
        """
        An Anthropic thinking-first AIMessage projects to its answer text.
        """
        runnable = self._make_runnable()
        output = runnable.parse_chain_result(ContentFixtures.anthropic_thinking_first(), exception=None)
        self.assertEqual(output, "the answer")

    def test_parse_chain_result_concatenates_text_blocks(self):
        """
        Text blocks after the first must not be dropped: the old flatten
        stopped at the first type=="text" block and returned "part one, ".
        """
        runnable = self._make_runnable()
        message = ContentFixtures.multi_text_blocks()
        self.assertEqual(runnable.parse_chain_result(message, exception=None), "part one, part two")

    def test_parse_chain_result_list_of_str_returns_full_text(self):
        """
        List-of-strings content is legal per the pydantic annotation; the old
        flatten skipped non-dict items and returned "".
        """
        runnable = self._make_runnable()
        output = runnable.parse_chain_result(ContentFixtures.list_of_str(), exception=None)
        self.assertEqual(output, "part one, part two")

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
        self.assertEqual(runnable.parse_chain_result(chain_result, exception=None), "the answer")

    def test_find_ai_message_returns_last_ai_message_in_dict(self) -> None:
        """
        The normal chain result is a dict whose "messages" hold chat history;
        the LAST AIMessage there is the answer, even when non-AI messages
        follow it.
        """
        first: AIMessage = AIMessage(content="first")
        last: AIMessage = AIMessage(content="last")
        chain_result: Dict[str, Any] = {
            "messages": [HumanMessage(content="q"), first, last, HumanMessage(content="x")],
        }
        self.assertIs(RunContextRunnable.find_ai_message(chain_result), last)

    def test_find_ai_message_passes_through_ai_message(self) -> None:
        """
        A bare AIMessage result is the answer itself.
        """
        message: AIMessage = AIMessage(content="the answer")
        self.assertIs(RunContextRunnable.find_ai_message(message), message)

    def test_find_ai_message_unwraps_agent_finish(self) -> None:
        """
        An AgentFinish result is unwrapped to its return_values first.
        """
        native: AIMessage = ContentFixtures.anthropic_thinking_first()
        finish: AgentFinish = AgentFinish(return_values={"messages": [HumanMessage(content="q"), native]}, log="")
        self.assertIs(RunContextRunnable.find_ai_message(finish), native)

    def test_find_ai_message_returns_none_without_ai_message(self) -> None:
        """
        A dict with no AIMessage (the API-key and output-parse error paths
        return {"output": ...}), a None result, and a messages list without
        an AIMessage all yield None.
        """
        self.assertIsNone(RunContextRunnable.find_ai_message({"output": "Please set OPENAI_API_KEY"}))
        self.assertIsNone(RunContextRunnable.find_ai_message({"messages": [HumanMessage(content="q")]}))
        self.assertIsNone(RunContextRunnable.find_ai_message(None))

    def test_parse_chain_result_bare_output_dict_returns_output(self) -> None:
        """
        A chain result with no AIMessage but an "output" key parses to that
        text, exactly as before the lookup moved into find_ai_message.
        """
        runnable = self._make_runnable()
        output: str = runnable.parse_chain_result({"output": "Please set OPENAI_API_KEY"}, exception=None)
        self.assertEqual(output, "Please set OPENAI_API_KEY")

    def test_parse_chain_result_agent_finish_with_output_key(self) -> None:
        """
        An AgentFinish whose return_values carry only an "output" key parses to
        that text: the unwrap applies on the fallback path too.
        """
        runnable = self._make_runnable()
        finish: AgentFinish = AgentFinish(return_values={"output": "done"}, log="")
        self.assertEqual(runnable.parse_chain_result(finish, exception=None), "done")

    async def test_parse_chain_result_matches_on_llm_end_projection(self):
        """
        The dupe-leak regression: parse_chain_result and
        JournalingCallbackHandler.on_llm_end must project the same block
        content to the same text, because OriginatingJournal suppresses the
        held AGENT message only when the next AI message carries the same
        content. The projections agree up to leading/trailing whitespace,
        which the journal's dupe comparison ignores (covered in
        test_originating_journal.py).
        """
        message = ContentFixtures.multi_text_blocks()

        runnable = self._make_runnable()
        parsed: str = runnable.parse_chain_result(message, exception=None)
        self.assertEqual(parsed, "part one, part two")

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
        self.assertEqual(journaled.content, parsed)

    async def test_journal_retry_reason_writes_agent_framework_message(self):
        """
        journal_retry_reason should write a single AgentFrameworkMessage carrying the
        client-facing reason plus the error class name. AgentFrameworkMessage is the
        right type because it is excluded from chat history (no token bloat) and is
        written through this agent's journal (so it carries an origin and is never
        mistaken for the final answer).
        """
        written: List[BaseMessage] = []
        mock_journal = MagicMock()
        mock_journal.write_message = AsyncMock(side_effect=partial(TestRunContextRunnable._record, written))
        sensitive_logger = MagicMock()
        sensitive_logger.should_log = MagicMock(return_value=True)

        runnable = RunContextRunnable.model_construct(
            journal=mock_journal,
            sensitive_logger=sensitive_logger
        )

        await runnable.journal_retry_reason(ValueError("bad json"), "the model's output could not be parsed")

        self.assertEqual(len(written), 1)
        message = written[0]
        self.assertIsInstance(message, AgentFrameworkMessage)
        self.assertEqual(message.content, "Retrying: the model's output could not be parsed (ValueError) - bad json")

    async def test_invoke_agent_chain_surfaces_retry_reason_before_final_message(self):
        """
        When a recoverable error is retried until attempts are exhausted, each retry
        should emit an AgentFrameworkMessage diagnostic, and the final AIMessage must
        still come last so the journal stream order is preserved.
        """
        written: List[BaseMessage] = []
        mock_journal = MagicMock()
        mock_journal.write_message = AsyncMock(side_effect=partial(TestRunContextRunnable._record, written))
        sensitive_logger = MagicMock()
        sensitive_logger.should_log = MagicMock(return_value=True)

        # A non-parse ValueError exercises the retry branch on every attempt.
        agent_chain = MagicMock()
        agent_chain.ainvoke = AsyncMock(side_effect=ValueError("not a parsing error"))

        # error_detector.handle_error is a pass-through for this test.
        error_detector = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=TestRunContextRunnable._passthrough)

        runnable = RunContextRunnable.model_construct(
            journal=mock_journal,
            sensitive_logger=sensitive_logger,
            agent_chain=agent_chain,
            error_detector=error_detector,
            logger=MagicMock(),
        )

        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=2)

        # Two retries -> two diagnostics, then the final AIMessage.
        self.assertEqual(len(written), 3)
        for msg in written[:2]:
            self.assertIsInstance(msg, AgentFrameworkMessage)
            self.assertEqual(msg.content,
                             "Retrying: the model's output could not be parsed (ValueError) - not a parsing error")
        self.assertIsInstance(written[-1], AIMessage)

    async def test_invoke_agent_chain_keeps_backtrace_out_of_client_output(self):
        """
        When the agent chain dies with an unhandled exception (e.g. an MCP tool
        transport error), the client-facing message must carry only the exception
        message: the full backtrace goes to the server log, not to the
        ErrorDetector as client-facing details.
        See https://github.com/cognizant-ai-lab/neuro-san/issues/1097
        """
        written: List[BaseMessage] = []
        mock_journal = MagicMock()
        mock_journal.write_message = AsyncMock(side_effect=partial(TestRunContextRunnable._record, written))
        sensitive_logger = MagicMock()
        sensitive_logger.should_log = MagicMock(return_value=True)

        # A RuntimeError exercises the non-retryable broad-exception branch.
        agent_chain = MagicMock()
        agent_chain.ainvoke = AsyncMock(side_effect=RuntimeError("Server error '504 Gateway Time-out'"))

        # error_detector.handle_error is a pass-through for this test.
        error_detector = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=TestRunContextRunnable._passthrough)

        runnable = RunContextRunnable.model_construct(
            journal=mock_journal,
            sensitive_logger=sensitive_logger,
            agent_chain=agent_chain,
            error_detector=error_detector,
            logger=MagicMock(),
        )

        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=3)

        # Unhandled exceptions are not retried: a single final AIMessage.
        self.assertEqual(len(written), 1)
        final = written[-1]
        self.assertIsInstance(final, AIMessage)
        self.assertEqual(final.content, "Agent stopped due to exception Server error '504 Gateway Time-out'")
        # The ErrorDetector must not receive the backtrace as client-facing details.
        error_detector.handle_error.assert_called_once_with(
            "Agent stopped due to exception Server error '504 Gateway Time-out'")
        # The backtrace is logged server-side instead.
        self.assertTrue(self._logged_traceback(sensitive_logger))

    async def test_invoke_agent_chain_does_not_log_stale_backtrace(self):
        """
        A backtrace captured on an earlier attempt must not be logged when a
        later attempt fails via a branch that captures no backtrace: any logged
        traceback must correspond to the exception that ended the retry loop.
        Here attempt 1 fails with a KeyError (captures a backtrace) and
        attempt 2 fails with a rate-limit error (captures none), so no
        traceback should be logged at all.
        """
        written: List[BaseMessage] = []
        mock_journal = MagicMock()
        mock_journal.write_message = AsyncMock(side_effect=partial(TestRunContextRunnable._record, written))
        sensitive_logger = MagicMock()
        sensitive_logger.should_log = MagicMock(return_value=True)

        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(429, request=request)
        rate_limit_error = RateLimitError("rate limited", response=response, body=None)

        agent_chain = MagicMock()
        agent_chain.ainvoke = AsyncMock(side_effect=[KeyError("missing field"), rate_limit_error])

        # error_detector.handle_error is a pass-through for this test.
        error_detector = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=TestRunContextRunnable._passthrough)

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
        self.assertIsInstance(final, AIMessage)
        self.assertIn("rate limited", final.content)
        # ...so the stale KeyError traceback from attempt 1 must not be logged.
        self.assertFalse(self._logged_traceback(sensitive_logger))

    @staticmethod
    def _make_invoking_runnable(chain_result: Any,
                                error_detector: MagicMock = None) -> Tuple[RunContextRunnable, List[BaseMessage]]:
        """
        Build a runnable whose agent chain returns the given result and whose
        journal records every written message.

        :param chain_result: What agent_chain.ainvoke should return
        :param error_detector: Optional error detector; defaults to a pass-through
        :return: The runnable and the list its journal appends written messages to
        """
        written: List[BaseMessage] = []
        journal: MagicMock = MagicMock()
        journal.write_message = AsyncMock(side_effect=partial(TestRunContextRunnable._record, written))
        agent_chain: MagicMock = MagicMock()
        agent_chain.ainvoke = AsyncMock(return_value=chain_result)
        if error_detector is None:
            error_detector = MagicMock()
            error_detector.handle_error = MagicMock(side_effect=TestRunContextRunnable._passthrough)
        sensitive_logger: MagicMock = MagicMock()
        sensitive_logger.should_log = MagicMock(return_value=True)
        runnable: RunContextRunnable = RunContextRunnable.model_construct(
            journal=journal,
            sensitive_logger=sensitive_logger,
            agent_chain=agent_chain,
            error_detector=error_detector,
            logger=MagicMock(),
        )
        return runnable, written

    @staticmethod
    def _block_types(message: BaseMessage) -> List[str]:
        """
        :param message: A message whose content is a list of block dictionaries
        :return: The "type" of each block, in order
        """
        block_types: List[str] = []
        for block in message.content:
            block_types.append(block["type"])
        return block_types

    async def test_invoke_agent_chain_preserves_block_content_answer(self) -> None:
        """
        A thinking-first native answer is journaled as the native message with
        its content normalized to standard blocks, not as a fresh text-only
        AIMessage: the reasoning and the usage metadata survive into the
        journal while the text it projects to is unchanged.
        """
        usage: Dict[str, int] = {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12}
        native: AIMessage = ContentFixtures.anthropic_thinking_first().model_copy(update={"usage_metadata": usage})
        runnable, written = self._make_invoking_runnable({"messages": [HumanMessage(content="q"), native]})
        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=1)

        final: BaseMessage = written[-1]
        self.assertIsInstance(final.content, list)
        self.assertEqual(self._block_types(final), ["reasoning", "text"])
        self.assertEqual(ContentUtils.flatten_to_text(final), "the answer")
        self.assertEqual(final.response_metadata["output_version"], "v1")
        self.assertEqual(final.response_metadata["model_provider"], "anthropic")
        self.assertEqual(final.usage_metadata, usage)

    async def test_invoke_agent_chain_keeps_text_only_answer_shape(self) -> None:
        """
        A plain-string native answer keeps the shape it has always had: a fresh
        AIMessage carrying only the text, without the native message's provider
        bookkeeping (id, metadata) that it never carried before.
        """
        native: AIMessage = AIMessage(content="the answer", id="msg_1",
                                      response_metadata={"model_provider": "openai"},
                                      usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
        runnable, written = self._make_invoking_runnable({"messages": [native]})
        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=1)

        final: BaseMessage = written[-1]
        self.assertIsInstance(final, AIMessage)
        self.assertEqual(final.content, "the answer")
        self.assertIsNone(final.id)
        self.assertEqual(final.response_metadata, {})
        self.assertIsNone(final.usage_metadata)

    async def test_invoke_agent_chain_error_rewrite_wins_over_native_blocks(self) -> None:
        """
        When the ErrorDetector rewrites the answer text, the journaled message
        carries the formatted error as plain text even though the native
        message had block content: the client-visible answer is the error.
        """
        error_detector: MagicMock = MagicMock()
        error_detector.handle_error = MagicMock(return_value="formatted error")
        runnable, written = self._make_invoking_runnable(ContentFixtures.anthropic_thinking_first(), error_detector)
        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=1)

        final: BaseMessage = written[-1]
        self.assertEqual(final.content, "formatted error")

    async def test_invoke_agent_chain_preserved_answer_excludes_tool_call_blocks(self) -> None:
        """
        A preserved block-content answer that still carries a tool call (the
        loop was cut short) keeps its reasoning and text blocks but no
        tool_use block: tool calls are not message content.
        """
        native: AIMessage = AIMessage(
            content=[
                {"type": "thinking", "thinking": "hmm", "signature": "sig"},
                {"type": "text", "text": "the answer"},
                {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"q": "x"}},
            ],
            tool_calls=[{"name": "lookup", "args": {"q": "x"}, "id": "toolu_1", "type": "tool_call"}],
            response_metadata={"model_provider": "anthropic"},
        )
        runnable, written = self._make_invoking_runnable(native)
        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=1)

        final: BaseMessage = written[-1]
        self.assertEqual(self._block_types(final), ["reasoning", "text"])
        self.assertEqual(ContentUtils.flatten_to_text(final), "the answer")

    async def test_invoke_agent_chain_tool_use_turn_collapses_to_text(self) -> None:
        """
        A text + tool_use native answer (every Anthropic tool-calling turn
        without reasoning) is text-only once tool calls are set aside, so it
        keeps the fresh AIMessage shape: no id, no metadata, no tool calls.
        """
        runnable, written = self._make_invoking_runnable({"messages": [ContentFixtures.anthropic_tool_use()]})
        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=1)

        final: BaseMessage = written[-1]
        self.assertIsInstance(final, AIMessage)
        self.assertEqual(final.content, "Let me look that up.")
        self.assertIsNone(final.id)
        self.assertEqual(final.response_metadata, {})
        self.assertEqual(final.tool_calls, [])

    async def test_invoke_agent_chain_list_of_str_answer_collapses_to_text(self) -> None:
        """
        List-of-strings native content carries no block structure, so it is
        journaled as the joined plain text.
        """
        runnable, written = self._make_invoking_runnable({"messages": [ContentFixtures.list_of_str()]})
        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=1)

        final: BaseMessage = written[-1]
        self.assertEqual(final.content, "part one, part two")
        self.assertIsNone(final.id)

    async def test_invoke_agent_chain_bare_output_dict_stays_text(self) -> None:
        """
        A chain result with no AIMessage, only an "output" key (the API-key
        and output-parse error paths), is journaled as that text.
        """
        runnable, written = self._make_invoking_runnable({"output": "Please set OPENAI_API_KEY"})
        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=1)

        final: BaseMessage = written[-1]
        self.assertIsInstance(final, AIMessage)
        self.assertEqual(final.content, "Please set OPENAI_API_KEY")
        self.assertIsNone(final.id)

    async def test_invoke_agent_chain_unwraps_agent_finish(self) -> None:
        """
        An AgentFinish result is unwrapped to its return_values, so a native
        block-content answer inside it is preserved the same way.
        """
        finish: AgentFinish = AgentFinish(
            return_values={"messages": [HumanMessage(content="q"), ContentFixtures.anthropic_thinking_first()]},
            log="")
        runnable, written = self._make_invoking_runnable(finish)
        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=1)

        final: BaseMessage = written[-1]
        self.assertEqual(self._block_types(final), ["reasoning", "text"])
        self.assertEqual(ContentUtils.flatten_to_text(final), "the answer")

    async def test_invoke_agent_chain_mixed_content_falls_back_to_text(self) -> None:
        """
        When normalizing would lose text (langchain's provider translators skip
        a bare string inside a block list), the answer is journaled as the
        full parsed text rather than as lossy blocks.
        """
        native: AIMessage = AIMessage(
            content=[
                "hello ",
                {"type": "thinking", "thinking": "hmm", "signature": "sig"},
                {"type": "text", "text": "world"},
            ],
            response_metadata={"model_provider": "anthropic"},
        )
        runnable, written = self._make_invoking_runnable({"messages": [native]})
        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=1)

        final: BaseMessage = written[-1]
        self.assertEqual(final.content, "hello world")

    async def test_invoke_agent_chain_chunk_answer_is_journaled_as_message(self) -> None:
        """
        An AIMessageChunk answer (only a custom middleware could produce one)
        is journaled as a complete AIMessage with its blocks preserved, so the
        journaled answer keeps the AI wire type.
        """
        native: AIMessageChunk = AIMessageChunk(
            content=[
                {"type": "thinking", "thinking": "hmm", "signature": "sig"},
                {"type": "text", "text": "the answer"},
            ],
            response_metadata={"model_provider": "anthropic"},
        )
        runnable, written = self._make_invoking_runnable({"messages": [native]})
        await runnable.invoke_agent_chain(inputs={}, runnable_config={}, max_attempts=1)

        final: BaseMessage = written[-1]
        self.assertIs(type(final), AIMessage)
        self.assertEqual(self._block_types(final), ["reasoning", "text"])
        self.assertEqual(ContentUtils.flatten_to_text(final), "the answer")
