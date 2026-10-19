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

from neuro_san.message.utils.tool_pairing import ToolPairing


class TestToolPairing(TestCase):
    """
    Tests for ToolPairing: a restored chat history keeps tool calls and tool
    results only in complete pairs.
    """

    @staticmethod
    def tool_call(call_id: str) -> Dict[str, Any]:
        """
        :param call_id: The id of the tool call
        :return: A langchain tool call dictionary for the Accountant tool
        """
        return {
            "name": "Accountant",
            "args": {"running_cost": 0.0},
            "id": call_id,
            "type": "tool_call",
        }

    def test_complete_pairs_keeps_a_whole_history_as_it_is(self) -> None:
        """
        Plain messages and a fully answered tool round pass through as the same instances.
        """
        calling: AIMessage = AIMessage(content="", tool_calls=[self.tool_call("c1"), self.tool_call("c2")])
        messages: List[BaseMessage] = [
            HumanMessage(content="question"),
            calling,
            ToolMessage(content="3.0", tool_call_id="c1"),
            ToolMessage(content="6.0", tool_call_id="c2"),
            AIMessage(content="answer"),
        ]

        kept: List[BaseMessage] = ToolPairing.complete_pairs(messages)

        self.assertEqual(len(kept), len(messages))
        index: int = None
        message: BaseMessage = None
        # Every message comes back as the very same object.
        for index, message in enumerate(messages):
            self.assertIs(kept[index], message)

    def test_complete_pairs_drops_a_result_without_its_call(self) -> None:
        """
        A tool result whose call is not the message right before it is dropped,
        whether it comes first or answers an id no call made.
        """
        messages: List[BaseMessage] = [
            ToolMessage(content="orphan", tool_call_id="c0"),
            HumanMessage(content="question"),
            AIMessage(content="", tool_calls=[self.tool_call("c1")]),
            ToolMessage(content="3.0", tool_call_id="c1"),
            ToolMessage(content="stray", tool_call_id="c9"),
            AIMessage(content="answer"),
        ]

        kept: List[BaseMessage] = ToolPairing.complete_pairs(messages)

        self.assertEqual(len(kept), 4)
        self.assertIsInstance(kept[0], HumanMessage)
        self.assertEqual(kept[1].tool_calls, [self.tool_call("c1")])
        self.assertEqual(kept[2].tool_call_id, "c1")
        self.assertEqual(kept[3].content, "answer")

    def test_complete_pairs_strips_an_unanswered_call(self) -> None:
        """
        A message whose calls are only partly answered keeps the answered calls
        and their results, in call order.
        """
        calling: AIMessage = AIMessage(content="Let me check.",
                                       tool_calls=[self.tool_call("c1"), self.tool_call("c2")])
        messages: List[BaseMessage] = [
            calling,
            ToolMessage(content="6.0", tool_call_id="c2"),
        ]

        kept: List[BaseMessage] = ToolPairing.complete_pairs(messages)

        self.assertEqual(len(kept), 2)
        self.assertIsNot(kept[0], calling)
        self.assertEqual(kept[0].content, "Let me check.")
        self.assertEqual(kept[0].tool_calls, [self.tool_call("c2")])
        self.assertEqual(kept[1].tool_call_id, "c2")

    def test_complete_pairs_drops_an_empty_message_whose_calls_are_all_unanswered(self) -> None:
        """
        A call-only message with no result left to pair is dropped altogether,
        while a message with text of its own stays, without its calls.
        """
        messages: List[BaseMessage] = [
            AIMessage(content="", tool_calls=[self.tool_call("c1")]),
            AIMessage(content="I asked the Accountant.", tool_calls=[self.tool_call("c2")]),
            AIMessage(content="answer"),
        ]

        kept: List[BaseMessage] = ToolPairing.complete_pairs(messages)

        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0].content, "I asked the Accountant.")
        self.assertEqual(kept[0].tool_calls, [])
        self.assertEqual(kept[1].content, "answer")
