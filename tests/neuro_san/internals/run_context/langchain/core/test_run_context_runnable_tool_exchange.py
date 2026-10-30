
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

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.tool import ToolMessage

from neuro_san.internals.run_context.langchain.core.run_context_runnable import RunContextRunnable

from tests.neuro_san.internals.run_context.langchain.core.run_context_runnable_test_helpers import \
    RunContextRunnableTestHelpers


class TestRunContextRunnableToolExchange(IsolatedAsyncioTestCase):
    """
    Tests for how RunContextRunnable records a turn's tool calls and results
    in the chat history: finding the turn's exchanges in the chain state,
    pairing each call with its result, leaving out what this turn already
    recorded, and recording while the chain streams its states.
    """

    @staticmethod
    def _tool_call(call_id: str) -> Dict[str, Any]:
        """
        Builds a tool call dictionary for the Accountant tool.

        :param call_id: The id of the tool call
        :return: A langchain tool call dictionary for the Accountant tool
        """
        return {
            "name": "Accountant",
            "args": {"running_cost": 0.0},
            "id": call_id,
            "type": "tool_call",
        }

    @staticmethod
    def _tool_turn_state(human: HumanMessage) -> Dict[str, Any]:
        """
        Builds a chain state for a turn in which the model called a tool once.

        :param human: The user's message that started the turn
        :return: A state dict whose messages are an earlier exchange, the user's
                 message, a tool-calling AIMessage with Anthropic-shaped content,
                 the ToolMessage answering it, and the answer
        """
        tool_call: Dict[str, Any] = TestRunContextRunnableToolExchange._tool_call("toolu_1")
        content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": "Let me check.",
            },
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "Accountant",
                "input": {"running_cost": 0.0},
            },
        ]
        calling: AIMessage = AIMessage(content=content, tool_calls=[tool_call])
        result: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="toolu_1", name="Accountant")
        return {"messages": [HumanMessage(content="earlier", id="h0"), AIMessage(content="earlier answer", id="a0"),
                             human, calling, result, AIMessage(content="the answer")]}

    def test_find_tool_exchange_pairs_call_with_result(self) -> None:
        """
        The turn's tool-calling AIMessage and the ToolMessage answering it are
        returned in order, the call's content projected to its text with the
        tool calls kept, and the answer left out.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()

        exchange: List[BaseMessage] = runnable.find_tool_exchange({"messages": [human]},
                                                                  self._tool_turn_state(human))

        self.assertEqual(len(exchange), 2)
        self.assertIsInstance(exchange[0], AIMessage)
        self.assertEqual(exchange[0].content, "Let me check.")
        self.assertEqual(exchange[0].tool_calls, [self._tool_call("toolu_1")])
        self.assertIsInstance(exchange[1], ToolMessage)
        self.assertEqual(exchange[1].content, "{'running_cost': 3.0}")
        self.assertEqual(exchange[1].tool_call_id, "toolu_1")

    def test_find_tool_exchange_drops_call_without_result(self) -> None:
        """
        A tool call that has no ToolMessage answering it, as after a step limit,
        is left out, since providers reject a call without its result.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        calling: AIMessage = AIMessage(content="", tool_calls=[self._tool_call("toolu_1")])
        state: Dict[str, Any] = {"messages": [human, calling, AIMessage(content="", tool_calls=[
            self._tool_call("toolu_2")])]}
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()

        self.assertEqual(runnable.find_tool_exchange({"messages": [human]}, state), [])

    def test_find_tool_exchange_drops_message_with_repeated_call_id(self) -> None:
        """
        An AIMessage whose tool calls share an id is left out even though a
        result exists for it, since providers reject or merge repeated ids.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        calling: AIMessage = AIMessage(content="", tool_calls=[self._tool_call("toolu_1"),
                                                               self._tool_call("toolu_1")])
        result: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="toolu_1")
        state: Dict[str, Any] = {"messages": [human, calling, result, AIMessage(content="the answer")]}
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()

        self.assertEqual(runnable.find_tool_exchange({"messages": [human]}, state), [])

    def test_find_tool_exchange_projects_empty_list_content_to_empty_text(self) -> None:
        """
        A tool-calling AIMessage with empty list content, as the OpenAI Responses
        API returns for a call-only turn, is kept with empty string content, so
        its dictionary carries a text key and survives the history processor.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        calling: AIMessage = AIMessage(content=[], tool_calls=[self._tool_call("call_1")])
        result: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="call_1")
        state: Dict[str, Any] = {"messages": [human, calling, result, AIMessage(content="the answer")]}
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()

        exchange: List[BaseMessage] = runnable.find_tool_exchange({"messages": [human]}, state)

        self.assertEqual(len(exchange), 2)
        self.assertEqual(exchange[0].content, "")
        self.assertEqual(exchange[0].tool_calls, [self._tool_call("call_1")])

    def test_find_tool_exchange_skips_exchange_already_in_history(self) -> None:
        """
        A tool round that a summarization already copied into the shared history,
        state messages and all, is not appended a second time.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        state: Dict[str, Any] = self._tool_turn_state(human)
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()
        # What the summarization middleware leaves behind: the state's own messages.
        runnable.chat_history = [human, state["messages"][3], state["messages"][4]]

        self.assertEqual(runnable.find_tool_exchange({"messages": [human]}, state), [])

        runnable.chat_history = [human]
        self.assertEqual(len(runnable.find_tool_exchange({"messages": [human]}, state)), 2)

    def test_record_tool_exchange_keeps_a_round_that_reuses_an_earlier_turn_call_id(self) -> None:
        """
        A round whose call id is the same as a call from an earlier turn is recorded,
        and only once: only what this turn added counts as already recorded.
        """
        earlier_call: AIMessage = AIMessage(content="", tool_calls=[self._tool_call("call_1")])
        earlier_result: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="call_1")
        earlier: List[BaseMessage] = [HumanMessage(content="earlier", id="h0"), earlier_call, earlier_result,
                                      AIMessage(content="earlier answer", id="a0")]
        human: HumanMessage = HumanMessage(content="question", id="h1")
        # As in wait_on_run(), the inputs hold the same message objects as the history.
        inputs: Dict[str, Any] = {"messages": earlier + [human]}
        new_call: AIMessage = AIMessage(content="", tool_calls=[self._tool_call("call_1")])
        new_result: ToolMessage = ToolMessage(content="{'running_cost': 6.0}", tool_call_id="call_1")
        state: Dict[str, Any] = {"messages": inputs.get("messages") + [new_call, new_result]}
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()
        runnable.chat_history = earlier + [human]

        # Every later state still holds the round, so it is seen twice here.
        runnable.record_tool_exchange(inputs, state)
        runnable.record_tool_exchange(inputs, state)

        self.assertEqual(len(runnable.chat_history), 7)
        self.assertEqual(runnable.chat_history[5].tool_calls, [self._tool_call("call_1")])
        self.assertEqual(runnable.chat_history[6].content, "{'running_cost': 6.0}")

    def test_find_tool_exchange_keeps_the_result_status(self) -> None:
        """
        A result that reports a failed tool keeps its error status in the history
        copy, so the model is told on replay that the tool failed.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        calling: AIMessage = AIMessage(content="", tool_calls=[self._tool_call("toolu_1")])
        failed: ToolMessage = ToolMessage(content="denied", tool_call_id="toolu_1", status="error")
        state: Dict[str, Any] = {"messages": [human, calling, failed, AIMessage(content="the answer")]}
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()

        exchange: List[BaseMessage] = runnable.find_tool_exchange({"messages": [human]}, state)

        self.assertEqual(exchange[1].status, "error")

    def test_find_tool_exchange_without_tool_calls_is_empty(self) -> None:
        """
        A turn that only answered adds nothing to the history beyond the answer itself.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        state: Dict[str, Any] = {"messages": [human, AIMessage(content="the answer")]}
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()

        self.assertEqual(runnable.find_tool_exchange({"messages": [human]}, state), [])
        self.assertEqual(runnable.find_tool_exchange({"messages": [human]}, AIMessage(content="bare")), [])

    def test_find_turn_start_matches_by_id_then_falls_back_to_last_human(self) -> None:
        """
        The turn's user message is found by identity or id; when a middleware
        replaced the list and neither matches, the last HumanMessage is used.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        copy_of_human: HumanMessage = HumanMessage(content="question", id="h1")
        messages: List[BaseMessage] = [HumanMessage(content="earlier", id="h0"), copy_of_human,
                                       AIMessage(content="the answer")]

        self.assertEqual(RunContextRunnable.find_turn_start({"messages": [human]}, messages), 1)
        self.assertEqual(RunContextRunnable.find_turn_start({"messages": [HumanMessage(content="other", id="hx")]},
                                                            messages), 1)
        self.assertEqual(RunContextRunnable.find_turn_start({}, [AIMessage(content="no human")]), -1)

    @staticmethod
    def _record_history_length(lengths: List[int], chat_history: List[BaseMessage],
                               message: BaseMessage, *_args: Any, **_kwargs: Any) -> None:
        """
        Note how many messages the chat history holds when the journal is written to,
        standing in for Journal.write_message.

        :param lengths: The list that collects the chat history length at each write
        :param chat_history: The chat history being watched
        :param message: The message being journaled (ignored)
        :param _args: Further positional arguments write_message accepts; ignored
        :param _kwargs: Further keyword arguments write_message accepts; ignored
        """
        _ = message
        lengths.append(len(chat_history))

    async def test_invoke_agent_chain_appends_tool_exchange_before_answer(self) -> None:
        """
        The tool call and its result are appended to the chat history before the
        answer is journaled, so the history reads call, result, answer.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        chat_history: List[BaseMessage] = []
        lengths: List[int] = []
        journal: MagicMock = MagicMock()
        journal.write_message = AsyncMock(side_effect=partial(self._record_history_length, lengths, chat_history))
        agent_chain: MagicMock = MagicMock()
        tool_turn: Dict[str, Any] = self._tool_turn_state(human)
        agent_chain.astream = MagicMock(side_effect=partial(RunContextRunnableTestHelpers.stream_of, tool_turn))
        error_detector: MagicMock = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=RunContextRunnableTestHelpers.passthrough)
        runnable: RunContextRunnable = RunContextRunnable.model_construct(
            journal=journal, chat_history=chat_history, agent_chain=agent_chain,
            error_detector=error_detector, logger=MagicMock(), sensitive_logger=MagicMock())

        await runnable.invoke_agent_chain({"messages": [human]}, {}, 1)

        self.assertEqual(lengths, [2])
        self.assertIsInstance(chat_history[0], AIMessage)
        self.assertEqual(chat_history[0].tool_calls, [self._tool_call("toolu_1")])
        self.assertIsInstance(chat_history[1], ToolMessage)

    async def test_invoke_agent_chain_records_tool_exchange_when_a_later_step_fails(self) -> None:
        """
        A tool round that completed before a later step failed is in the history when
        the error answer is journaled: it was recorded from the state the chain reached.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        state: Dict[str, Any] = self._tool_turn_state(human)
        reached: Dict[str, Any] = {"messages": state["messages"][:-1]}  # the round is done, no answer yet
        chat_history: List[BaseMessage] = []
        lengths: List[int] = []
        journal: MagicMock = MagicMock()
        journal.write_message = AsyncMock(side_effect=partial(self._record_history_length, lengths, chat_history))
        agent_chain: MagicMock = MagicMock()
        agent_chain.astream = MagicMock(side_effect=partial(RunContextRunnableTestHelpers.stream_of, reached,
                                                            RuntimeError("Server error '504 Gateway Time-out'")))
        error_detector: MagicMock = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=RunContextRunnableTestHelpers.passthrough)
        sensitive_logger: MagicMock = MagicMock()
        sensitive_logger.should_log = MagicMock(return_value=True)
        runnable: RunContextRunnable = RunContextRunnable.model_construct(
            journal=journal, chat_history=chat_history, agent_chain=agent_chain,
            error_detector=error_detector, logger=MagicMock(), sensitive_logger=sensitive_logger)

        await runnable.invoke_agent_chain({"messages": [human]}, {}, 1)

        self.assertEqual(lengths, [2])
        self.assertEqual(chat_history[0].tool_calls, [self._tool_call("toolu_1")])
        self.assertIsInstance(chat_history[1], ToolMessage)
        self.assertEqual(chat_history[1].tool_call_id, "toolu_1")

    async def test_invoke_agent_chain_records_a_round_compacted_out_of_the_state(self) -> None:
        """
        A tool round recorded from an earlier state stays in the history when a later
        state no longer holds it, as after a summarization; the next round is recorded once.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        first_call: AIMessage = AIMessage(content="", tool_calls=[self._tool_call("toolu_1")])
        first_result: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="toolu_1")
        second_call: AIMessage = AIMessage(content="", tool_calls=[self._tool_call("toolu_2")])
        second_result: ToolMessage = ToolMessage(content="{'running_cost': 6.0}", tool_call_id="toolu_2")
        summary: HumanMessage = HumanMessage(content="Here is a summary of the conversation to date.", id="s1")
        before: Dict[str, Any] = {"messages": [human, first_call, first_result]}
        after: Dict[str, Any] = {"messages": [summary, second_call, second_result, AIMessage(content="the answer")]}
        chat_history: List[BaseMessage] = []
        lengths: List[int] = []
        journal: MagicMock = MagicMock()
        journal.write_message = AsyncMock(side_effect=partial(self._record_history_length, lengths, chat_history))
        agent_chain: MagicMock = MagicMock()
        agent_chain.astream = MagicMock(side_effect=partial(RunContextRunnableTestHelpers.stream_of, before, after))
        error_detector: MagicMock = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=RunContextRunnableTestHelpers.passthrough)
        runnable: RunContextRunnable = RunContextRunnable.model_construct(
            journal=journal, chat_history=chat_history, agent_chain=agent_chain,
            error_detector=error_detector, logger=MagicMock(), sensitive_logger=MagicMock())

        await runnable.invoke_agent_chain({"messages": [human]}, {}, 1)

        self.assertEqual(lengths, [4])
        self.assertEqual(chat_history[0].tool_calls, [self._tool_call("toolu_1")])
        self.assertEqual(chat_history[1].tool_call_id, "toolu_1")
        self.assertEqual(chat_history[2].tool_calls, [self._tool_call("toolu_2")])
        self.assertEqual(chat_history[3].tool_call_id, "toolu_2")
