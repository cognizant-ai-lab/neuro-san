
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

from asyncio import Task
from asyncio import TimeoutError as AsyncTimeout
from asyncio import create_task
from asyncio import sleep as async_sleep
from contextlib import contextmanager
from functools import partial

from typing import Any
from typing import Awaitable
from typing import Dict
from typing import Generator
from typing import List
from typing import Optional

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage

from neuro_san.internals.run_context.langchain.token_counting.langchain_token_counter import LangChainTokenCounter
from neuro_san.message.types.agent_message import AgentMessage


class TestTokenCounterTimeout(IsolatedAsyncioTestCase):
    """
    Tests for the LangChainTokenCounter.count_tokens() timeout path: what the counter journals when
    the awaitable runs past max_execution_seconds.
    """

    CALLBACK_PATH: str = (
        "neuro_san.internals.run_context.langchain.token_counting.langchain_token_counter.get_llm_token_callback"
    )

    # count_tokens() gives up after MAX_EXECUTION_SECONDS; the awaitable sleeps far longer.
    MAX_EXECUTION_SECONDS: float = 0.05
    SLOW_AWAITABLE_SECONDS: float = 10.0

    async def test_count_tokens_timeout_writes_aimessage_before_token_accounting_and_raises(self) -> None:
        """
        On AsyncTimeout (asyncio.TimeoutError), count_tokens should:
        1. Write a final AIMessage to the journal BEFORE report() writes its
           token-accounting AgentMessages, so the journal stream order matches
           the normal-completion path.
        2. Re-raise AsyncTimeout so the caller (RunContextRunnable.run_it) can
           log/handle it.
        """
        # Capture journal.write_message arguments in call order.
        written_messages: List[BaseMessage] = []
        # Single-element origin on a non-cloned context -> report() takes the
        # main-front-man branch and writes the two request-level messages.
        origin: List[Dict[str, Any]] = [
            {
                "tool": "test_agent",
                "instantiation_index": 0
            }
        ]
        counter: LangChainTokenCounter = TestTokenCounterTimeout._make_counter(origin, written_messages)
        await self._count_tokens_until_timeout(counter)

        # 1) First journal write must be the synthesized timeout AIMessage.
        self.assertTrue(written_messages, "Expected at least the timeout AIMessage on the journal")
        first_message: AIMessage = written_messages[0]
        self.assertIsInstance(first_message, AIMessage, "First journal message should be AIMessage")
        self.assertIn("max_execution_seconds", first_message.content)

        # 2) The subsequent messages are the front man's two token-accounting
        #    AgentMessages (main network, then request total).
        written_message_count: int = len(written_messages)
        self.assertEqual(written_message_count, 3, "Expected 2 request-level AgentMessages after the timeout AIMessage")
        message: BaseMessage
        # Every message after the timeout AIMessage is a token-accounting AgentMessage.
        for message in written_messages[1:]:
            self.assertIsInstance(message, AgentMessage, "Expected AgentMessage after AIMessage")

    async def test_count_tokens_timeout_agent_branch_writes_per_agent_message(self) -> None:
        """
        A timed-out non-front-man agent (multi-element origin) still writes its
        per-agent token accounting message after the synthesized AIMessage.
        """
        written_messages: List[BaseMessage] = []
        # Multi-element origin -> report() takes the per-agent else-branch.
        origin: List[Dict[str, Any]] = [
            {
                "tool": "front_man",
                "instantiation_index": 0
            },
            {
                "tool": "slow_agent",
                "instantiation_index": 0
            }
        ]
        counter: LangChainTokenCounter = TestTokenCounterTimeout._make_counter(origin, written_messages)
        await self._count_tokens_until_timeout(counter)

        # Timeout AIMessage first, then exactly one per-agent AgentMessage.
        written_message_count: int = len(written_messages)
        self.assertEqual(written_message_count, 2)
        self.assertIsInstance(written_messages[0], AIMessage)
        agent_message: AgentMessage = written_messages[1]
        self.assertIsInstance(agent_message, AgentMessage)
        caveats: List[str] = agent_message.structure.get("caveats")
        self.assertIn("tracked at the agent level", caveats[0])

    async def _count_tokens_until_timeout(self, counter: LangChainTokenCounter) -> None:
        """
        Run counter.count_tokens() on an awaitable that outlives MAX_EXECUTION_SECONDS, with the token
        callback patched out, and check that it raises AsyncTimeout.

        :param counter: The LangChainTokenCounter under test
        """
        max_execution_seconds: float = TestTokenCounterTimeout.MAX_EXECUTION_SECONDS
        slow_awaitable: Awaitable = TestTokenCounterTimeout._slow_awaitable()
        with patch(TestTokenCounterTimeout.CALLBACK_PATH, TestTokenCounterTimeout._fake_token_callback):
            with self.assertRaises(AsyncTimeout):
                await counter.count_tokens(slow_awaitable, max_execution_seconds=max_execution_seconds)

    @staticmethod
    def _make_counter(origin: List[Dict[str, Any]], written_messages: List[BaseMessage]) -> LangChainTokenCounter:
        """
        Build a LangChainTokenCounter whose journal records every message and whose
        executor runs a real asyncio.Task, so count_tokens() really times out.

        :param origin: The origin the counter applies to all messages
        :param written_messages: The list that collects every journaled message, in order
        :return: The LangChainTokenCounter under test
        """
        mock_journal: MagicMock = MagicMock()
        record_message: partial = partial(TestTokenCounterTimeout._record, written_messages)
        mock_journal.write_message = AsyncMock(side_effect=record_message)

        # Mock the invocation_context dependencies that count_tokens / report touch.
        mock_invocation_context: MagicMock = MagicMock()
        mock_invocation_context.get_llm_factory.return_value.get_llm_infos.return_value = {}
        mock_invocation_context.get_request_reporting.return_value = {}
        # Not a clone: report() writes the network token message for front men.
        mock_invocation_context.is_cloned.return_value = False

        # The executor wraps the awaitable in a real asyncio.Task so
        # asyncio.wait_for() actually times out and cancels it.
        mock_executor: MagicMock = MagicMock()
        mock_executor.create_task.side_effect = TestTokenCounterTimeout._create_real_task
        mock_invocation_context.get_asyncio_executor.return_value = mock_executor

        mock_llm: MagicMock = MagicMock()
        counter: LangChainTokenCounter = LangChainTokenCounter(
            llm=mock_llm,
            invocation_context=mock_invocation_context,
            journal=mock_journal,
            origin=origin
        )
        return counter

    @staticmethod
    def _record(written_messages: List[BaseMessage], message: BaseMessage,
                _origin: Optional[List[Dict[str, Any]]] = None) -> None:
        """
        Append the given message to the written list, standing in for OriginatingJournal.write_message()
        so tests can inspect everything the counter journaled.

        :param written_messages: The list that collects every journaled message, in order
        :param message: The message being journaled
        :param _origin: The origin OriginatingJournal.write_message() accepts; ignored
        """
        written_messages.append(message)

    @staticmethod
    def _create_real_task(awaitable: Awaitable, _submitter_id: str, _raise_exception: bool = False) -> Task:
        """
        Stand in for TaskExecutor.create_task() by wrapping the awaitable in a real asyncio.Task.

        :param awaitable: The awaitable to run
        :param _submitter_id: The submitter id create_task() accepts; ignored
        :param _raise_exception: The raise_exception flag create_task() accepts; ignored
        :return: The running asyncio.Task
        """
        task: Task = create_task(awaitable)
        return task

    @staticmethod
    async def _slow_awaitable() -> None:
        """
        Sleep long enough that every count_tokens() timeout in these tests fires first.
        """
        await async_sleep(TestTokenCounterTimeout.SLOW_AWAITABLE_SECONDS)

    @staticmethod
    @contextmanager
    def _fake_token_callback(_llm_infos: Dict[str, Any]) -> Generator[MagicMock, None, None]:
        """
        Stand in for get_llm_token_callback() with a callback that holds zero token counts.

        :param _llm_infos: The llm_infos get_llm_token_callback() accepts; ignored
        :return: A generator that yields the zero-count callback once
        """
        zero_count_callback: MagicMock = MagicMock()
        zero_count_callback.models_token_dict = {}
        zero_count_callback.total_tokens = 0
        zero_count_callback.prompt_tokens = 0
        zero_count_callback.completion_tokens = 0
        zero_count_callback.successful_requests = 0
        zero_count_callback.empty_responses = 0
        zero_count_callback.total_cost = 0.0
        yield zero_count_callback
