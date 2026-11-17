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


from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.tool import ToolMessage

from neuro_san.message.utils.content_utils import ContentUtils


class ToolPairing:
    """
    Keeps the tool calls and tool results of a chat history in complete pairs.

    A provider rejects a tool result whose call is missing and a tool call whose
    result is missing. A history restored from a chat_context can hold either:
    a client may have cut it, or a call may have been dropped as malformed on
    the way in. Each tool-calling AI message keeps only the calls that the tool
    results right after it answer, and only those results are kept. Each call
    or result that is dropped is logged at info level, by its id.
    """

    @staticmethod
    def complete_pairs(messages: List[BaseMessage]) -> List[BaseMessage]:
        """
        Drops the tool calls and tool results that have no partner.

        :param messages: The messages of a chat history, in order
        :return: The same messages with every tool call answered by a tool result
                 right after its message, and no tool result without its call
        """
        kept: List[BaseMessage] = []
        index: int = 0
        # A tool-calling message and the results right after it are handled together.
        while index < len(messages):
            message: BaseMessage = messages[index]
            if isinstance(message, ToolMessage):
                # A result with no call before it.
                ToolPairing.log_dropped_result(message)
                index += 1
                continue
            calls_tools: bool = ToolPairing.makes_tool_calls(message)
            if not calls_tools:
                kept.append(message)
                index += 1
                continue
            next_index: int = index + 1
            results: List[ToolMessage] = ToolPairing.results_after(messages, next_index)
            paired: List[BaseMessage] = ToolPairing.pair(message, results)
            kept.extend(paired)
            # Move past the message and the results that follow it.
            result_count: int = len(results)
            index = next_index + result_count
        return kept

    @staticmethod
    def makes_tool_calls(message: BaseMessage) -> bool:
        """
        Tells whether a message is an AI message that made tool calls.

        :param message: The message to examine
        :return: True for an AIMessage with at least one tool call
        """
        if not isinstance(message, AIMessage):
            return False
        call_count: int = len(message.tool_calls)
        return call_count > 0

    @staticmethod
    def results_after(messages: List[BaseMessage], start: int) -> List[ToolMessage]:
        """
        Collects the tool results that directly follow a tool-calling message.

        :param messages: The messages of a chat history
        :param start: The index right after a tool-calling message
        :return: The run of ToolMessages that starts there, possibly empty
        """
        results: List[ToolMessage] = []
        index: int = start
        # Results follow their call with nothing in between.
        while index < len(messages):
            message: BaseMessage = messages[index]
            if not isinstance(message, ToolMessage):
                break
            results.append(message)
            index += 1
        return results

    @staticmethod
    def pair(message: AIMessage, results: List[ToolMessage]) -> List[BaseMessage]:
        """
        Pairs a tool-calling message with the results that follow it.

        Each result answers one call. When two results answer the same call, the
        later one is kept. A call that repeats an id already answered finds no
        result left and is treated as unanswered.

        :param message: An AIMessage with tool calls
        :param results: The ToolMessages right after it
        :return: The message with only its answered calls, followed by the results
                 of those calls in call order. Empty when no call was answered and
                 the message has no text of its own.
        """
        by_id: Dict[str, ToolMessage] = {}
        # Index the results by the call they answer. A later result for the same call replaces the earlier one.
        result: ToolMessage = None
        for result in results:
            replaced: Optional[ToolMessage] = by_id.get(result.tool_call_id, None)
            if replaced is not None:
                ToolPairing.log_dropped_result(replaced)
            by_id[result.tool_call_id] = result

        answered_calls: List[Dict[str, Any]] = []
        answered_results: List[ToolMessage] = []
        # Keep each call that has a result, together with that result.
        tool_call: Dict[str, Any] = None
        for tool_call in message.tool_calls:
            call_id: str = tool_call.get("id")
            answer: Optional[ToolMessage] = by_id.get(call_id, None)
            if answer is None:
                ToolPairing.log_dropped_call(tool_call)
                continue
            # Each result is used once, so a repeated call id finds nothing left.
            del by_id[call_id]
            answered_calls.append(tool_call)
            answered_results.append(answer)

        # The results left over answer none of the calls.
        for result in by_id.values():
            ToolPairing.log_dropped_result(result)

        kept_message: Optional[AIMessage] = message
        call_count: int = len(message.tool_calls)
        answered_count: int = len(answered_calls)
        if answered_count < call_count:
            kept_message = ToolPairing.with_calls(message, answered_calls)

        paired: List[BaseMessage] = []
        if kept_message is not None:
            paired.append(kept_message)
        paired.extend(answered_results)
        return paired

    @staticmethod
    def with_calls(message: AIMessage, calls: List[Dict[str, Any]]) -> Optional[AIMessage]:
        """
        Copies a tool-calling message so that it carries only the given calls.

        :param message: An AIMessage with tool calls
        :param calls: The calls to keep
        :return: A copy of the message carrying only those calls, or None when no
                 call remains and the message has no text either
        """
        if len(calls) == 0:
            text: str = ContentUtils.flatten_to_text(message)
            if text == "":
                return None
        update: Dict[str, Any] = {"tool_calls": calls}
        return ContentUtils.message_model_copy(message, update)

    @staticmethod
    def log_dropped_call(tool_call: Dict[str, Any]) -> None:
        """
        Logs a tool call that is dropped because no tool result answers it.

        :param tool_call: The dropped tool call
        """
        # Logged at info: the client sent this history, and no one running the server can act on it.
        # The arguments are not logged: a client's call can carry secrets.
        call_id: str = tool_call.get("id")
        name: str = tool_call.get("name")
        logger: Logger = getLogger(ToolPairing.__name__)
        logger.info("Dropping a tool call in chat_context that has no result (id %r, name %r)", call_id, name)

    @staticmethod
    def log_dropped_result(result: ToolMessage) -> None:
        """
        Logs a tool result that is dropped because it is not paired with a call:
        no call before it asked for it, or a later result answers the same call.

        :param result: The dropped tool result
        """
        # Logged at info for the same reason as log_dropped_call().
        # The content is not logged: a tool result can carry secrets.
        logger: Logger = getLogger(ToolPairing.__name__)
        logger.info("Dropping a tool result in chat_context that is not paired with a call (tool_call_id %r)",
                    result.tool_call_id)
