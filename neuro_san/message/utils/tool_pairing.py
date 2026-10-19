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
    results right after it answer, and only those results are kept.
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
                index += 1
                continue
            if not isinstance(message, AIMessage) or not message.tool_calls:
                kept.append(message)
                index += 1
                continue
            results: List[ToolMessage] = ToolPairing.results_after(messages, index + 1)
            kept.extend(ToolPairing.pair(message, results))
            index += 1 + len(results)
        return kept

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
        while index < len(messages) and isinstance(messages[index], ToolMessage):
            results.append(messages[index])
            index += 1
        return results

    @staticmethod
    def pair(message: AIMessage, results: List[ToolMessage]) -> List[BaseMessage]:
        """
        Pairs a tool-calling message with the results that follow it.

        Each result answers one call. A call that repeats an id already answered
        finds no result left and is treated as unanswered.

        :param message: An AIMessage with tool calls
        :param results: The ToolMessages right after it
        :return: The message with only its answered calls, followed by the results
                 of those calls in call order. Empty when no call was answered and
                 the message has no text of its own.
        """
        by_id: Dict[str, ToolMessage] = {}
        # Index the results by the call they answer.
        result: ToolMessage = None
        for result in results:
            by_id[result.tool_call_id] = result

        answered_calls: List[Dict[str, Any]] = []
        answered_results: List[ToolMessage] = []
        # Keep each call that has a result, together with that result, using each result once.
        tool_call: Dict[str, Any] = None
        for tool_call in message.tool_calls:
            result = by_id.pop(tool_call.get("id"), None)
            if result is not None:
                answered_calls.append(tool_call)
                answered_results.append(result)

        kept_message: Optional[AIMessage] = message
        if len(answered_calls) < len(message.tool_calls):
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
        if len(calls) == 0 and ContentUtils.flatten_to_text(message) == "":
            return None
        update: Dict[str, Any] = {"tool_calls": calls}
        return ContentUtils.message_model_copy(message, update)
