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
from typing import Optional
from typing import Set
from typing import Union

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.tool import ToolMessage

from neuro_san.message.utils.content_utils import ContentUtils


class ToolExchangeRecorder:
    """
    Records each turn's tool calls and their results in an agent's chat history,
    so the next turn's model sees which values came from tools.

    RunContextRunnable passes it every state the agent chain streams. The state
    is the only record of the tool calls the model made.

    A plain class, not a pydantic model, so it appends to the RunContext's own
    list rather than a copy.
    """

    def __init__(self, chat_history: Optional[List[BaseMessage]]) -> None:
        """
        Creates a recorder that appends to the given chat history in place.

        :param chat_history: The RunContext's own chat history, or None when no history is kept
        """
        self.chat_history: Optional[List[BaseMessage]] = chat_history

    def record_tool_exchange(self, inputs: Dict[str, Any],
                             chain_result: Optional[Union[Dict[str, Any], AIMessage]]) -> None:
        """
        Appends the new complete tool rounds of one chain state to the chat history,
        ahead of the answer that is journaled next.

        :param inputs: The inputs the agent chain was invoked with
        :param chain_result: A state streamed from the agent chain
        """
        if self.chat_history is None:
            return
        exchange: List[BaseMessage] = self.find_tool_exchange(inputs, chain_result)
        # Append in place: the list is shared with the RunContext.
        message: BaseMessage = None
        for message in exchange:
            self.chat_history.append(message)

    def find_tool_exchange(self, inputs: Dict[str, Any],
                           chain_result: Optional[Union[Dict[str, Any], AIMessage]]) \
            -> List[BaseMessage]:
        """
        Picks the new complete tool rounds out of one chain state.

        A round is a tool-calling AIMessage followed by the ToolMessage of each of its
        calls. A round with a missing result is left out, since providers reject a call
        without its result. Rounds this turn already recorded are skipped, and so is the
        turn's answer, which is journaled separately.

        :param inputs: The inputs the agent chain was invoked with
        :param chain_result: A state streamed from the agent chain
        :return: Copies of the new rounds' messages with history-safe text, in order.
                 Empty when there is nothing new to record.
        """
        if not isinstance(chain_result, dict):
            return []
        messages: List[BaseMessage] = chain_result.get("messages", [])
        start: int = ToolExchangeRecorder.find_turn_start(inputs, messages)
        if start < 0:
            return []
        turn: List[BaseMessage] = ToolExchangeRecorder.turn_after(messages, start)
        recorded_keys: Set[str] = self.recorded_round_keys(inputs)

        exchange: List[BaseMessage] = []
        # Each new tool-calling AIMessage goes in followed by the results of its calls.
        index: int = 0
        message: BaseMessage = None
        for index, message in enumerate(turn):
            if not isinstance(message, AIMessage):
                continue
            if len(message.tool_calls) == 0:
                continue
            if ToolExchangeRecorder.is_recorded(message, recorded_keys):
                continue
            next_index: int = index + 1
            round_tool_messages: List[ToolMessage] = ToolExchangeRecorder.round_results(turn, next_index)
            results: Dict[str, ToolMessage] = ToolExchangeRecorder.results_by_call_id(round_tool_messages)
            paired: Optional[List[ToolMessage]] = ToolExchangeRecorder.paired_results(message, results)
            if paired is None:
                # A call without its result would be rejected on replay.
                continue
            round_copy: List[BaseMessage] = ToolExchangeRecorder.copy_round(message, paired)
            exchange.extend(round_copy)
        return exchange

    @staticmethod
    def turn_after(messages: List[BaseMessage], start: int) -> List[BaseMessage]:
        """
        Gives the messages the turn added after the user's message, up to its answer.

        :param messages: The messages of a chain state
        :param start: The index of the turn's user message
        :return: The messages after the user's message, without the answer
        """
        turn_start: int = start + 1
        after_human: List[BaseMessage] = messages[turn_start:]
        turn: List[BaseMessage] = ToolExchangeRecorder.before_answer(after_human)
        return turn

    @staticmethod
    def copy_round(message: AIMessage, paired: List[ToolMessage]) -> List[BaseMessage]:
        """
        Copies a tool round for the chat history, with history-safe text.

        :param message: The AIMessage that made the calls
        :param paired: The results of its calls, in call order
        :return: The copy of the AIMessage followed by the copies of its results
        """
        round_copy: List[BaseMessage] = []
        # The copy keeps the message id, which marks the round as recorded.
        call_text: str = ContentUtils.history_safe_text(message)
        call_copy: AIMessage = AIMessage(content=call_text, tool_calls=message.tool_calls, id=message.id)
        round_copy.append(call_copy)
        # Each result keeps its status: some providers tell the model when a call failed.
        result: ToolMessage = None
        for result in paired:
            result_text: str = ContentUtils.history_safe_text(result)
            result_copy: ToolMessage = ToolMessage(content=result_text,
                                                   tool_call_id=result.tool_call_id,
                                                   status=result.status)
            round_copy.append(result_copy)
        return round_copy

    def recorded_round_keys(self, inputs: Dict[str, Any]) -> Set[str]:
        """
        Collects the keys of the tool rounds this turn has already put in the chat history.

        Only the messages after the turn's user message count. A model can give a new
        call the same id as a call from an earlier turn, and that call still has to be recorded.

        :param inputs: The inputs the agent chain was invoked with
        :return: The round_keys() of every tool round this turn added to the chat history.
                 Empty when no history is kept.
        """
        keys: Set[str] = set()
        if self.chat_history is None:
            # No history kept means nothing recorded.
            return keys
        history: List[BaseMessage] = self.chat_history
        # The user's message goes into the history before the chain runs. A summarization
        # that cuts it out cuts all earlier turns too, so then the whole history is this turn's.
        start: int = ToolExchangeRecorder.find_turn_start(inputs, history)
        index: int = start + 1
        # Collect the keys of every tool round after the turn's user message.
        while index < len(history):
            message: BaseMessage = history[index]
            index += 1
            if not isinstance(message, AIMessage):
                continue
            if len(message.tool_calls) == 0:
                continue
            message_keys: List[str] = ToolExchangeRecorder.round_keys(message)
            key: str = None
            # A round without a message id has one key per call.
            for key in message_keys:
                keys.add(key)
        return keys

    @staticmethod
    def round_keys(message: AIMessage) -> List[str]:
        """
        Gives the keys that tell a tool round apart from the other rounds of a turn.

        The key is the message id, since two rounds can share a call id. A message
        without an id is known by its call ids instead.

        :param message: An AIMessage with tool calls
        :return: The message id, or the ids of its tool calls when it has none,
                 each with a prefix that says which kind of id it is
        """
        keys: List[str] = []
        if message.id:
            message_key: str = f"message:{message.id}"
            keys.append(message_key)
            return keys
        # Without a message id, the round is known by its calls.
        tool_call: Dict[str, Any] = None
        for tool_call in message.tool_calls:
            call_id: Optional[str] = tool_call.get("id", None)
            call_key: str = f"call:{call_id}"
            keys.append(call_key)
        return keys

    @staticmethod
    def is_recorded(message: AIMessage, recorded_keys: Set[str]) -> bool:
        """
        Tells whether a tool round is already in the chat history.

        :param message: An AIMessage with tool calls
        :param recorded_keys: The round_keys() of the rounds the history already holds
        :return: True if any key of the message is among them
        """
        message_keys: List[str] = ToolExchangeRecorder.round_keys(message)
        # One shared key is enough: the whole round was copied together.
        key: str = None
        for key in message_keys:
            if key in recorded_keys:
                return True
        return False

    @staticmethod
    def round_results(turn: List[BaseMessage], start: int) -> List[ToolMessage]:
        """
        Collects the tool results of one round: the ToolMessages between its
        AIMessage and the next AIMessage of the turn.

        A later round can reuse a call id. Looking only within the round keeps each
        call paired with its own result.

        :param turn: The messages of a turn
        :param start: The index right after the round's AIMessage
        :return: The round's ToolMessages, in order
        """
        results: List[ToolMessage] = []
        index: int = start
        # The next AIMessage starts the next round.
        while index < len(turn):
            message: BaseMessage = turn[index]
            if isinstance(message, AIMessage):
                break
            if isinstance(message, ToolMessage):
                results.append(message)
            index += 1
        return results

    @staticmethod
    def before_answer(turn: List[BaseMessage]) -> List[BaseMessage]:
        """
        Cuts a turn's messages off at its answer, a trailing AIMessage without tool calls.

        :param turn: The messages the turn added after the user's message
        :return: The messages before the answer, or all of them while there is no answer yet
        """
        if len(turn) == 0:
            return turn
        last: BaseMessage = turn[-1]
        if not isinstance(last, AIMessage):
            return turn
        if len(last.tool_calls) > 0:
            # A trailing AIMessage that made tool calls is not an answer: the turn is still under way.
            return turn
        before: List[BaseMessage] = turn[:-1]
        return before

    @staticmethod
    def results_by_call_id(messages: List[BaseMessage]) -> Dict[str, ToolMessage]:
        """
        Indexes tool results by the call each one answers.

        :param messages: The messages to look through, such as the results of one round
        :return: The ToolMessages among them, by the id of the tool call each one answers
        """
        results: Dict[str, ToolMessage] = {}
        # Index the results by the call they answer.
        message: BaseMessage = None
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            if not message.tool_call_id:
                continue
            results[message.tool_call_id] = message
        return results

    @staticmethod
    def paired_results(message: AIMessage, results: Dict[str, ToolMessage]) -> Optional[List[ToolMessage]]:
        """
        Finds the result of every tool call an AIMessage made.

        Call ids must be unique within the message. Providers reject or quietly
        merge repeated ids on replay, so a message that repeats one is not kept.

        :param message: An AIMessage with tool calls
        :param results: The round's ToolMessages by tool call id
        :return: One ToolMessage per tool call, in call order, or None when any
                 call has no result or two calls share an id
        """
        paired: List[ToolMessage] = []
        seen_ids: Set[str] = set()
        # Look up the result of each call, in call order.
        tool_call: Dict[str, Any] = None
        for tool_call in message.tool_calls:
            call_id: Optional[str] = tool_call.get("id", None)
            if call_id in seen_ids:
                return None
            seen_ids.add(call_id)
            result: Optional[ToolMessage] = results.get(call_id, None)
            if result is None:
                return None
            paired.append(result)
        return paired

    @staticmethod
    def find_turn_start(inputs: Dict[str, Any], messages: List[BaseMessage]) -> int:
        """
        Finds the user's message that started this turn.

        It is the last input message, found by identity or by id. When neither
        matches, as after a middleware replaced the messages, the last HumanMessage
        is used instead.

        :param inputs: The inputs the agent chain was invoked with
        :param messages: The messages to search: a chain state's or the chat history
        :return: The index of the turn's user message, or -1 when there is none
        """
        human: Optional[BaseMessage] = None
        if isinstance(inputs, dict):
            input_messages: List[BaseMessage] = inputs.get("messages", [])
            if len(input_messages) > 0:
                human = input_messages[-1]

        last_index: int = len(messages) - 1
        index: int = None
        if human is not None:
            human_id: Optional[str] = human.id
            # Search from the end: the turn's user message is the last one of the inputs.
            for index in range(last_index, -1, -1):
                message: BaseMessage = messages[index]
                if message is human:
                    return index
                if human_id is None:
                    # Without an id, only the identity check can match.
                    continue
                if message.id == human_id:
                    return index

        # Fall back to the last HumanMessage.
        for index in range(last_index, -1, -1):
            candidate: BaseMessage = messages[index]
            if isinstance(candidate, HumanMessage):
                return index
        return -1
