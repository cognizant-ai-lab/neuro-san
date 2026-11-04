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

from neuro_san.internals.run_context.langchain.core.langchain_run_context import LangChainRunContext
from neuro_san.message.types.chat_message_type import ChatMessageType


class TestLangChainRunContext(TestCase):
    """
    Tests for LangChainRunContext: restoring a chat history from a chat_context.
    """

    ORIGIN: List[Dict[str, Any]] = [
        {
            "tool": "front_man",
            "instantiation_index": 1,
        },
    ]

    @staticmethod
    def make_run_context() -> LangChainRunContext:
        """
        Builds a LangChainRunContext with just the state that restoring a
        chat_context reads, bypassing __init__ and its resource wiring.

        :return: A run context for the front man with an empty chat history
        """
        run_context: LangChainRunContext = LangChainRunContext.__new__(LangChainRunContext)
        run_context.origin = TestLangChainRunContext.ORIGIN
        run_context.chat_history = []
        return run_context

    def test_update_from_chat_context_drops_a_message_whose_calls_are_all_malformed(self) -> None:
        """
        A call-only AI entry whose only call is malformed, and the result that
        answered it, both stay out of the restored history, which then holds the
        user's message and the answer alone.
        """
        messages: List[Dict[str, Any]] = [
            {
                "type": ChatMessageType.HUMAN,
                "text": "question",
            },
            {
                "type": ChatMessageType.AI,
                "text": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "",
                        "args": {},
                    },
                ],
            },
            {
                "type": ChatMessageType.AGENT_TOOL_RESULT,
                "text": "orphan",
                "tool_call_id": "c1",
            },
            {
                "type": ChatMessageType.AI,
                "text": "answer",
            },
        ]
        chat_context: Dict[str, Any] = {
            "chat_histories": [
                {
                    "origin": self.ORIGIN,
                    "messages": messages,
                },
            ],
        }
        run_context: LangChainRunContext = self.make_run_context()

        with self.assertLogs("BaseMessageDictionaryConverter", level="WARNING"):
            run_context.update_from_chat_context(chat_context)

        history: List[BaseMessage] = run_context.chat_history
        self.assertEqual(len(history), 2)
        self.assertIsInstance(history[0], HumanMessage)
        self.assertEqual(history[1].content, "answer")

    def test_update_from_chat_context_keeps_only_complete_tool_pairs(self) -> None:
        """
        A chat_context that carries a malformed call with its result, and a good
        call with its result, restores to the good call, its result and the plain
        messages; the result of the dropped call does not come back on its own.
        """
        messages: List[Dict[str, Any]] = [
            {
                "type": ChatMessageType.HUMAN,
                "text": "question",
            },
            {
                "type": ChatMessageType.AI,
                "text": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "",
                        "args": {},
                    },
                    {
                        "id": "c2",
                        "name": "Accountant",
                        "args": {"running_cost": 0.0},
                    },
                ],
            },
            {
                "type": ChatMessageType.AGENT_TOOL_RESULT,
                "text": "orphan",
                "tool_call_id": "c1",
            },
            {
                "type": ChatMessageType.AGENT_TOOL_RESULT,
                "text": "{'running_cost': 3.0}",
                "tool_call_id": "c2",
            },
            {
                "type": ChatMessageType.AI,
                "text": "answer",
            },
        ]
        chat_context: Dict[str, Any] = {
            "chat_histories": [
                {
                    "origin": self.ORIGIN,
                    "messages": messages,
                },
            ],
        }
        run_context: LangChainRunContext = self.make_run_context()

        with self.assertLogs("BaseMessageDictionaryConverter", level="WARNING"):
            run_context.update_from_chat_context(chat_context)

        history: List[BaseMessage] = run_context.chat_history
        self.assertEqual(len(history), 4)
        self.assertIsInstance(history[0], HumanMessage)
        self.assertIsInstance(history[1], AIMessage)
        self.assertEqual(len(history[1].tool_calls), 1)
        self.assertEqual(history[1].tool_calls[0].get("id"), "c2")
        self.assertIsInstance(history[2], ToolMessage)
        self.assertEqual(history[2].tool_call_id, "c2")
        self.assertEqual(history[3].content, "answer")
