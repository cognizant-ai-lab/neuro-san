
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

from unittest import TestCase

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage

from neuro_san.internals.chat.chat_history_message_processor import ChatHistoryMessageProcessor
from neuro_san.message.types.base_message_dictionary_converter import BaseMessageDictionaryConverter
from neuro_san.message.types.chat_message_type import ChatMessageType


class TestChatHistoryMessageProcessor(TestCase):
    """
    Tests for ChatHistoryMessageProcessor: which messages go into the chat_context
    history, that their text is kept exactly as written, and that trimming with
    max_message_history never separates a tool call from its result.
    """

    TOOL_CALLS: List[Dict[str, Any]] = [
        {
            "id": "toolu_1",
            "name": "Accountant",
            "args": {"running_cost": 0.0},
        },
    ]

    @staticmethod
    def types_of(history: List[Dict[str, Any]]) -> List[ChatMessageType]:
        """
        :param history: A list of ChatMessage dictionaries
        :return: The type of each dictionary, in order
        """
        types: List[ChatMessageType] = []
        # Collect the type of each message, in order.
        message: Dict[str, Any] = None
        for message in history:
            types.append(message.get("type"))
        return types

    def test_keep_message_copies_text_unchanged(self) -> None:
        """
        Text goes into the history exactly as written, braces included, in a copy of the dictionary.
        """
        original: Dict[str, Any] = {
            "type": ChatMessageType.AI,
            "text": "a {b} and {{c}}",
        }

        result: Optional[Dict[str, Any]] = ChatHistoryMessageProcessor.keep_message(original)

        self.assertIsNotNone(result)
        self.assertIsNot(result, original)
        self.assertEqual(result, original)

    def test_keep_message_keeps_text_of_block_message(self) -> None:
        """
        A message that carries content_blocks keeps its text and its blocks, so
        the text still equals the flattened blocks and the message restores
        to its blocks on the next request, braces and all.
        """
        blocks: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": '{"ok": true}',
                "phase": "final_answer",
            },
        ]
        response_metadata: Dict[str, Any] = {
            "model_provider": "openai",
            "output_version": "v1",
        }
        message: AIMessage = AIMessage(content=blocks, response_metadata=response_metadata)
        converter: BaseMessageDictionaryConverter = BaseMessageDictionaryConverter()
        wire: Dict[str, Any] = converter.to_dict(message)
        self.assertIn("content_blocks", wire)

        result: Optional[Dict[str, Any]] = ChatHistoryMessageProcessor.keep_message(wire)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("text"), '{"ok": true}')
        self.assertEqual(result.get("content_blocks"), wire.get("content_blocks"))

        restored: BaseMessage = converter.from_dict(result)
        self.assertEqual(restored.content, blocks)

    def test_keep_message_passes_non_str_text_through(self) -> None:
        """
        Non-str text (block content) is kept as it is: the message is copied,
        not dropped, and its text still refers to the same blocks.
        """
        blocks: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": "{not escaped}",
            },
        ]
        original: Dict[str, Any] = {
            "type": ChatMessageType.AI,
            "text": blocks,
        }

        result: Optional[Dict[str, Any]] = ChatHistoryMessageProcessor.keep_message(original)

        self.assertIsNotNone(result)
        self.assertIsNot(result, original)
        self.assertIs(result.get("text"), blocks)
        self.assertEqual(result.get("type"), ChatMessageType.AI)

    def test_keep_message_without_text_returns_none(self) -> None:
        """
        A message with no text key at all is dropped from the history.
        """
        self.assertIsNone(ChatHistoryMessageProcessor.keep_message({"type": ChatMessageType.AI}))

    def test_process_message_keeps_tool_calls_on_ai_message(self) -> None:
        """
        An AI message that made tool calls keeps them in the history, text and all.
        """
        processor: ChatHistoryMessageProcessor = ChatHistoryMessageProcessor()
        message: Dict[str, Any] = {
            "type": ChatMessageType.AI,
            "text": "",
            "tool_calls": self.TOOL_CALLS,
        }

        processor.process_message(message, ChatMessageType.AI)

        self.assertEqual(processor.get_message_history(), [message])

    def test_process_message_keeps_tool_result_with_tool_call_id(self) -> None:
        """
        A tool result that names the call it answers goes into the history.
        """
        processor: ChatHistoryMessageProcessor = ChatHistoryMessageProcessor()
        message: Dict[str, Any] = {
            "type": ChatMessageType.AGENT_TOOL_RESULT,
            "text": "{'running_cost': 3.0}",
            "tool_call_id": "toolu_1",
        }

        processor.process_message(message, ChatMessageType.AGENT_TOOL_RESULT)

        self.assertEqual(processor.get_message_history(), [message])

    def test_process_message_drops_tool_result_without_tool_call_id(self) -> None:
        """
        A stand-alone tool result, with no call to pair it with, stays out of the history.
        """
        processor: ChatHistoryMessageProcessor = ChatHistoryMessageProcessor()
        message: Dict[str, Any] = {
            "type": ChatMessageType.AGENT_TOOL_RESULT,
            "text": "tool says",
        }

        processor.process_message(message, ChatMessageType.AGENT_TOOL_RESULT)

        self.assertEqual(processor.get_message_history(), [])

    def test_process_message_drops_agent_messages(self) -> None:
        """
        Framework-only message types never go into the history.
        """
        processor: ChatHistoryMessageProcessor = ChatHistoryMessageProcessor()
        agent: Dict[str, Any] = {
            "type": ChatMessageType.AGENT,
            "text": "thinking",
        }
        framework: Dict[str, Any] = {
            "type": ChatMessageType.AGENT_FRAMEWORK,
            "text": "done",
        }

        processor.process_message(agent, ChatMessageType.AGENT)
        processor.process_message(framework, ChatMessageType.AGENT_FRAMEWORK)

        self.assertEqual(processor.get_message_history(), [])

    def test_process_messages_trim_starts_at_a_user_message(self) -> None:
        """
        With max_message_history set, the kept tail starts at a user message, so a
        tool result is never left without the call that asked for it.
        """
        processor: ChatHistoryMessageProcessor = ChatHistoryMessageProcessor(max_message_history=3)
        messages: List[Dict[str, Any]] = [
            {
                "type": ChatMessageType.SYSTEM,
                "text": "instructions",
            },
            {
                "type": ChatMessageType.HUMAN,
                "text": "first question",
            },
            {
                "type": ChatMessageType.AI,
                "text": "",
                "tool_calls": self.TOOL_CALLS,
            },
            {
                "type": ChatMessageType.AGENT_TOOL_RESULT,
                "text": "{'running_cost': 3.0}",
                "tool_call_id": "toolu_1",
            },
            {
                "type": ChatMessageType.AI,
                "text": "first answer",
            },
            {
                "type": ChatMessageType.HUMAN,
                "text": "second question",
            },
            {
                "type": ChatMessageType.AI,
                "text": "second answer",
            },
        ]

        processor.process_messages(messages)

        # The last three are [first answer, second question, second answer]; the
        # answer before the question is dropped so the history starts at a user turn.
        history: List[Dict[str, Any]] = processor.get_message_history()
        self.assertEqual(self.types_of(history),
                         [ChatMessageType.SYSTEM, ChatMessageType.HUMAN, ChatMessageType.AI])
        self.assertEqual(history[0].get("text"), "<redacted>")
        self.assertEqual(history[1].get("text"), "second question")

    def test_process_messages_trim_drops_a_cut_tool_pair(self) -> None:
        """
        When the kept tail cuts into a tool round, the whole tail is dropped rather
        than sending a tool result with no call before it.
        """
        processor: ChatHistoryMessageProcessor = ChatHistoryMessageProcessor(max_message_history=2)
        messages: List[Dict[str, Any]] = [
            {
                "type": ChatMessageType.SYSTEM,
                "text": "instructions",
            },
            {
                "type": ChatMessageType.HUMAN,
                "text": "question",
            },
            {
                "type": ChatMessageType.AI,
                "text": "",
                "tool_calls": self.TOOL_CALLS,
            },
            {
                "type": ChatMessageType.AGENT_TOOL_RESULT,
                "text": "{'running_cost': 3.0}",
                "tool_call_id": "toolu_1",
            },
            {
                "type": ChatMessageType.AI,
                "text": "answer",
            },
        ]

        processor.process_messages(messages)

        self.assertEqual(self.types_of(processor.get_message_history()), [ChatMessageType.SYSTEM])
