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

from langchain_core.agents import AgentFinish
from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.tool import ToolMessage

from neuro_san.message.utils.content_utils import ContentUtils


class ToolExchangeRecorder:
    """
    Records each turn's tool calls and their results in an agent's chat history.

    The agent chain's state is the only record of the tool calls the model made.
    RunContextRunnable gives this class every state the chain streams, and this
    class appends each complete tool round to the chat history, ahead of the
    answer that is journaled next.

    This is a plain class, not a pydantic model: pydantic would store a copy of
    the list, and the appends would never reach the RunContext.
    """

    def __init__(self, chat_history: Optional[List[BaseMessage]]) -> None:
        """
        Creates a recorder that appends to the given chat history in place.

        :param chat_history: The RunContext's own chat history, or None when no history is kept
        """
        self.chat_history: Optional[List[BaseMessage]] = chat_history

    def record_tool_exchange(self, inputs: Dict[str, Any],
                             chain_result: Optional[Union[Dict[str, Any], AgentFinish, AIMessage]]) -> None:
        """
        Appends this turn's tool calls and their results to the chat history,
        ahead of the answer that is journaled next.

        The chain state is the only record of the tool calls the model made.
        Each result is journaled as it arrives, but on its own, with no link to
        the call that asked for it. Keeping the call and its result together in
        the history lets the next turn's model see where a value came from,
        instead of a bare number it might take for a guess.

        :param inputs: The inputs the agent chain was invoked with
        :param chain_result: The result from invoking the agent chain
        """
        if self.chat_history is None:
            return
        exchange: List[BaseMessage] = self.find_tool_exchange(inputs, chain_result)
        # Append in place: the list is shared with the RunContext.
        message: BaseMessage = None
        for message in exchange:
            self.chat_history.append(message)

    def find_tool_exchange(self, inputs: Dict[str, Any],
                           chain_result: Optional[Union[Dict[str, Any], AgentFinish, AIMessage]]) \
            -> List[BaseMessage]:
        """
        Picks this turn's tool calls and their results out of the chain state.

        Only complete pairs are kept: an AIMessage whose every tool call has a
        ToolMessage answering it, followed by those ToolMessages. Providers
        reject a tool call without its result, so a call cut short by an error
        or a step limit is left out. The answer, the last AIMessage of the turn,
        is not included; it is journaled separately. Contents are projected to
        history-safe text so no provider-native blocks reach another provider
        or the client.

        Each round of tool calls is handled on its own: its results are the
        ToolMessages between its AIMessage and the next one. A round this turn
        already put in the history is skipped: every later state still holds it,
        and a summarization that keeps the round in context copies it there first.
        Rounds are told apart by message id, which LangGraph gives every message in
        the state. So two rounds that share a call id are both kept, even when one
        of them comes from a retry.

        :param inputs: The inputs the agent chain was invoked with
        :param chain_result: The result from invoking the agent chain
        :return: The messages to append to the chat history, in order.
                 Empty when the turn made no tool calls.
        """
        if not isinstance(chain_result, dict):
            return []
        messages: List[BaseMessage] = chain_result.get("messages", [])
        start: int = ToolExchangeRecorder.find_turn_start(inputs, messages)
        if start < 0:
            return []

        turn: List[BaseMessage] = ToolExchangeRecorder.before_answer(messages[start + 1:])
        recorded_keys: Set[str] = self.recorded_round_keys(inputs)

        exchange: List[BaseMessage] = []
        # Each tool-calling AIMessage goes in followed by the results of its calls.
        index: int = 0
        message: BaseMessage = None
        for index, message in enumerate(turn):
            if not isinstance(message, AIMessage) or not message.tool_calls:
                continue
            if ToolExchangeRecorder.is_recorded(message, recorded_keys):
                continue
            round_tool_messages: List[ToolMessage] = ToolExchangeRecorder.round_results(turn, index + 1)
            results: Dict[str, ToolMessage] = ToolExchangeRecorder.results_by_call_id(round_tool_messages)
            paired: Optional[List[ToolMessage]] = ToolExchangeRecorder.paired_results(message, results)
            if paired is None:
                # A call without its result would be rejected on replay.
                continue
            # The copy keeps the message id, which marks the round as recorded.
            exchange.append(AIMessage(content=ContentUtils.history_safe_text(message),
                                      tool_calls=message.tool_calls,
                                      id=message.id))
            # Results follow their call, in call order. The status is kept: LangChain sets
            # "error" on a call it could not run, and some providers pass that on to the model.
            result: ToolMessage = None
            for result in paired:
                exchange.append(ToolMessage(content=ContentUtils.history_safe_text(result),
                                            tool_call_id=result.tool_call_id,
                                            status=result.status))
        return exchange

    def recorded_round_keys(self, inputs: Dict[str, Any]) -> Set[str]:
        """
        Collects the keys of the tool rounds this turn has already put in the chat history.

        Messages from earlier turns are left out. A model can give a new call the
        same id as a call from an earlier turn, and that call still has to be recorded.

        :param inputs: The inputs the agent chain was invoked with
        :return: The round_keys() of every tool round this turn added to the chat history.
                 Empty when no history is kept.
        """
        # wait_on_run() builds the inputs from a shallow copy of the history, so the
        # messages of earlier turns are the same objects in both lists.
        earlier: Set[int] = set()
        input_messages: List[BaseMessage] = []
        if isinstance(inputs, dict):
            input_messages = inputs.get("messages") or []
        message: BaseMessage = None
        # Note each input message by its identity.
        for message in input_messages:
            earlier.add(id(message))

        keys: Set[str] = set()
        # No history kept means nothing recorded.
        history: List[BaseMessage] = self.chat_history or []
        # Collect the keys of every tool round this turn added to the history.
        for message in history:
            if id(message) in earlier:
                continue
            if not isinstance(message, AIMessage) or not message.tool_calls:
                continue
            keys.update(ToolExchangeRecorder.round_keys(message))
        return keys

    @staticmethod
    def round_keys(message: AIMessage) -> List[str]:
        """
        Gives the keys that tell a tool round apart from the other rounds of a turn.

        LangGraph gives every message in the chain state an id, and the history copy
        of a round keeps it, so the message id is the key. Two rounds can share a call
        id, even across a retry, but each has its own message id. A message without an
        id is known by its call ids instead.

        :param message: An AIMessage with tool calls
        :return: The message id, or the ids of its tool calls when it has none,
                 each with a prefix that says which kind of id it is
        """
        if message.id:
            return [f"message:{message.id}"]
        keys: List[str] = []
        # Without a message id, the round is known by its calls.
        tool_call: Dict[str, Any] = None
        for tool_call in message.tool_calls:
            keys.append(f"call:{tool_call.get('id')}")
        return keys

    @staticmethod
    def is_recorded(message: AIMessage, recorded_keys: Set[str]) -> bool:
        """
        Tells whether a tool round is already in the chat history.

        :param message: An AIMessage with tool calls
        :param recorded_keys: The round_keys() of the rounds the history already holds
        :return: True if any key of the message is among them
        """
        # One shared key is enough: the whole round was copied together.
        key: str = None
        for key in ToolExchangeRecorder.round_keys(message):
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
        while index < len(turn) and not isinstance(turn[index], AIMessage):
            if isinstance(turn[index], ToolMessage):
                results.append(turn[index])
            index += 1
        return results

    @staticmethod
    def before_answer(turn: List[BaseMessage]) -> List[BaseMessage]:
        """
        Cuts a turn's messages off at its answer, a trailing AIMessage without tool calls.

        A trailing AIMessage that made tool calls is not an answer: the turn is
        still under way, and its results, when present, are paired like any other.

        :param turn: The messages the turn added after the user's message
        :return: The messages before the answer, or all of them while there is no answer yet
        """
        if len(turn) > 0 and isinstance(turn[-1], AIMessage) and not turn[-1].tool_calls:
            return turn[:-1]
        return turn

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
            if isinstance(message, ToolMessage) and message.tool_call_id:
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
            call_id: Optional[str] = tool_call.get("id")
            if call_id in seen_ids:
                return None
            seen_ids.add(call_id)
            result: Optional[ToolMessage] = results.get(call_id)
            if result is None:
                return None
            paired.append(result)
        return paired

    @staticmethod
    def find_turn_start(inputs: Dict[str, Any], messages: List[BaseMessage]) -> int:
        """
        Finds the user's message that started this turn in the chain state.

        The state holds the input messages followed by what the turn added, and
        the last input message is the user's. langgraph gives it an id in place,
        so it is found by identity or by id. When neither matches, because a
        middleware replaced the list, the last HumanMessage is used instead.

        :param inputs: The inputs the agent chain was invoked with
        :param messages: The messages from the chain state
        :return: The index of the turn's user message, or -1 when there is none
        """
        human: Optional[BaseMessage] = None
        if isinstance(inputs, dict):
            input_messages: List[BaseMessage] = inputs.get("messages", [])
            if len(input_messages) > 0:
                human = input_messages[-1]

        index: int = None
        if human is not None:
            # Search from the end: the turn's user message is the last one of the inputs.
            for index in range(len(messages) - 1, -1, -1):
                message: BaseMessage = messages[index]
                if message is human or (human.id is not None and message.id == human.id):
                    return index

        # Fall back to the last HumanMessage in the state.
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                return index
        return -1
