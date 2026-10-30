
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

from unittest import TestCase

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.tool import ToolMessage

from neuro_san.internals.run_context.langchain.core.tool_exchange_recorder import ToolExchangeRecorder

from tests.neuro_san.internals.run_context.langchain.core.run_context_runnable_test_helpers import \
    RunContextRunnableTestHelpers


class TestToolExchangeRecorder(TestCase):
    """
    Tests for how ToolExchangeRecorder records a turn's tool calls and results
    in the chat history: finding the turn's exchanges in the chain state,
    pairing each call with its result, and leaving out what this turn already
    recorded.
    """

    def test_find_tool_exchange_pairs_call_with_result(self) -> None:
        """
        The turn's tool-calling AIMessage and the ToolMessage answering it are
        returned in order, the call's content projected to its text with the
        tool calls kept, and the answer left out.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        recorder: ToolExchangeRecorder = ToolExchangeRecorder([])

        exchange: List[BaseMessage] = recorder.find_tool_exchange({"messages": [human]},
                                                                  RunContextRunnableTestHelpers.tool_turn_state(human))

        self.assertEqual(len(exchange), 2)
        self.assertIsInstance(exchange[0], AIMessage)
        self.assertEqual(exchange[0].content, "Let me check.")
        self.assertEqual(exchange[0].tool_calls, [RunContextRunnableTestHelpers.tool_call("toolu_1")])
        self.assertIsInstance(exchange[1], ToolMessage)
        self.assertEqual(exchange[1].content, "{'running_cost': 3.0}")
        self.assertEqual(exchange[1].tool_call_id, "toolu_1")

    def test_find_tool_exchange_drops_call_without_result(self) -> None:
        """
        A tool call that has no ToolMessage answering it, as after a step limit,
        is left out, since providers reject a call without its result.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        calling: AIMessage = AIMessage(content="", tool_calls=[RunContextRunnableTestHelpers.tool_call("toolu_1")])
        state: Dict[str, Any] = {"messages": [human, calling, AIMessage(content="", tool_calls=[
            RunContextRunnableTestHelpers.tool_call("toolu_2")])]}
        recorder: ToolExchangeRecorder = ToolExchangeRecorder([])

        self.assertEqual(recorder.find_tool_exchange({"messages": [human]}, state), [])

    def test_find_tool_exchange_drops_message_with_repeated_call_id(self) -> None:
        """
        An AIMessage whose tool calls share an id is left out even though a
        result exists for it, since providers reject or merge repeated ids.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        calling: AIMessage = AIMessage(content="", tool_calls=[RunContextRunnableTestHelpers.tool_call("toolu_1"),
                                                               RunContextRunnableTestHelpers.tool_call("toolu_1")])
        result: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="toolu_1")
        state: Dict[str, Any] = {"messages": [human, calling, result, AIMessage(content="the answer")]}
        recorder: ToolExchangeRecorder = ToolExchangeRecorder([])

        self.assertEqual(recorder.find_tool_exchange({"messages": [human]}, state), [])

    def test_find_tool_exchange_projects_empty_list_content_to_empty_text(self) -> None:
        """
        A tool-calling AIMessage with empty list content, as the OpenAI Responses
        API returns for a call-only turn, is kept with empty string content, so
        its dictionary carries a text key and survives the history processor.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        calling: AIMessage = AIMessage(content=[], tool_calls=[RunContextRunnableTestHelpers.tool_call("call_1")])
        result: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="call_1")
        state: Dict[str, Any] = {"messages": [human, calling, result, AIMessage(content="the answer")]}
        recorder: ToolExchangeRecorder = ToolExchangeRecorder([])

        exchange: List[BaseMessage] = recorder.find_tool_exchange({"messages": [human]}, state)

        self.assertEqual(len(exchange), 2)
        self.assertEqual(exchange[0].content, "")
        self.assertEqual(exchange[0].tool_calls, [RunContextRunnableTestHelpers.tool_call("call_1")])

    def test_find_tool_exchange_skips_exchange_already_in_history(self) -> None:
        """
        A tool round that a summarization already copied into the shared history,
        state messages and all, is not appended a second time.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        state: Dict[str, Any] = RunContextRunnableTestHelpers.tool_turn_state(human)
        # What the summarization middleware leaves behind: the state's own messages.
        recorder: ToolExchangeRecorder = ToolExchangeRecorder([human, state.get("messages")[3],
                                                               state.get("messages")[4]])

        self.assertEqual(recorder.find_tool_exchange({"messages": [human]}, state), [])

        recorder = ToolExchangeRecorder([human])
        self.assertEqual(len(recorder.find_tool_exchange({"messages": [human]}, state)), 2)

    def test_record_tool_exchange_keeps_a_round_that_reuses_an_earlier_turn_call_id(self) -> None:
        """
        A round whose call id is the same as a call from an earlier turn is recorded,
        and only once: only what this turn added counts as already recorded.
        """
        earlier_call: AIMessage = AIMessage(content="", tool_calls=[RunContextRunnableTestHelpers.tool_call("call_1")])
        earlier_result: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="call_1")
        earlier: List[BaseMessage] = [HumanMessage(content="earlier", id="h0"), earlier_call, earlier_result,
                                      AIMessage(content="earlier answer", id="a0")]
        human: HumanMessage = HumanMessage(content="question", id="h1")
        # As in wait_on_run(), the inputs hold the same message objects as the history.
        inputs: Dict[str, Any] = {"messages": earlier + [human]}
        new_call: AIMessage = AIMessage(content="", tool_calls=[RunContextRunnableTestHelpers.tool_call("call_1")])
        new_result: ToolMessage = ToolMessage(content="{'running_cost': 6.0}", tool_call_id="call_1")
        state: Dict[str, Any] = {"messages": inputs.get("messages") + [new_call, new_result]}
        chat_history: List[BaseMessage] = earlier + [human]
        recorder: ToolExchangeRecorder = ToolExchangeRecorder(chat_history)

        # Every later state still holds the round, so it is seen twice here.
        recorder.record_tool_exchange(inputs, state)
        recorder.record_tool_exchange(inputs, state)

        # The rounds went into the caller's own list.
        self.assertEqual(len(chat_history), 7)
        self.assertEqual(chat_history[5].tool_calls, [RunContextRunnableTestHelpers.tool_call("call_1")])
        self.assertEqual(chat_history[6].content, "{'running_cost': 6.0}")

    def test_find_tool_exchange_pairs_each_round_with_its_own_result(self) -> None:
        """
        Two rounds of one turn that reuse a call id each keep their own result,
        since a round's results are looked up only within that round.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        first_call: AIMessage = AIMessage(content="", tool_calls=[RunContextRunnableTestHelpers.tool_call("call_1")],
                                          id="ai_1")
        first_result: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="call_1")
        second_call: AIMessage = AIMessage(content="", tool_calls=[RunContextRunnableTestHelpers.tool_call("call_1")],
                                           id="ai_2")
        second_result: ToolMessage = ToolMessage(content="{'running_cost': 6.0}", tool_call_id="call_1")
        state: Dict[str, Any] = {"messages": [human, first_call, first_result, second_call, second_result,
                                              AIMessage(content="the answer", id="ai_3")]}
        recorder: ToolExchangeRecorder = ToolExchangeRecorder([])

        exchange: List[BaseMessage] = recorder.find_tool_exchange({"messages": [human]}, state)

        self.assertEqual(len(exchange), 4)
        self.assertEqual(exchange[1].content, "{'running_cost': 3.0}")
        self.assertEqual(exchange[3].content, "{'running_cost': 6.0}")
        # The copies keep the message ids, which mark the rounds as recorded.
        self.assertEqual(exchange[0].id, "ai_1")
        self.assertEqual(exchange[2].id, "ai_2")

    def test_find_tool_exchange_keeps_the_result_status(self) -> None:
        """
        A result that reports a failed tool keeps its error status in the history
        copy, so the model is told on replay that the tool failed.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        calling: AIMessage = AIMessage(content="", tool_calls=[RunContextRunnableTestHelpers.tool_call("toolu_1")])
        failed: ToolMessage = ToolMessage(content="denied", tool_call_id="toolu_1", status="error")
        state: Dict[str, Any] = {"messages": [human, calling, failed, AIMessage(content="the answer")]}
        recorder: ToolExchangeRecorder = ToolExchangeRecorder([])

        exchange: List[BaseMessage] = recorder.find_tool_exchange({"messages": [human]}, state)

        self.assertEqual(exchange[1].status, "error")

    def test_find_tool_exchange_without_tool_calls_is_empty(self) -> None:
        """
        A turn that only answered adds nothing to the history beyond the answer itself.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        state: Dict[str, Any] = {"messages": [human, AIMessage(content="the answer")]}
        recorder: ToolExchangeRecorder = ToolExchangeRecorder([])

        self.assertEqual(recorder.find_tool_exchange({"messages": [human]}, state), [])
        self.assertEqual(recorder.find_tool_exchange({"messages": [human]}, AIMessage(content="bare")), [])

    def test_find_turn_start_matches_by_id_then_falls_back_to_last_human(self) -> None:
        """
        The turn's user message is found by identity or id; when a middleware
        replaced the list and neither matches, the last HumanMessage is used.
        """
        human: HumanMessage = HumanMessage(content="question", id="h1")
        copy_of_human: HumanMessage = HumanMessage(content="question", id="h1")
        messages: List[BaseMessage] = [HumanMessage(content="earlier", id="h0"), copy_of_human,
                                       AIMessage(content="the answer")]

        self.assertEqual(ToolExchangeRecorder.find_turn_start({"messages": [human]}, messages), 1)
        self.assertEqual(ToolExchangeRecorder.find_turn_start({"messages": [HumanMessage(content="other", id="hx")]},
                                                              messages), 1)
        self.assertEqual(ToolExchangeRecorder.find_turn_start({}, [AIMessage(content="no human")]), -1)
