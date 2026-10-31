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
from langchain_core.messages.tool import ToolMessage

from neuro_san.message.types.base_message_dictionary_converter import BaseMessageDictionaryConverter
from neuro_san.message.types.chat_message_type import ChatMessageType


class TestBaseMessageDictionaryConverterToolCalls(TestCase):
    """
    Tests for how the wire converter carries tool calls and tool results.

    An AI message sends its tool calls as id, name and args, and a ToolMessage
    sends the id of the call it answers, plus tool_status when the tool failed.
    Coming back, a malformed call is left out with a warning, and a result
    without a call id is not restored for a chat history.
    """

    ORIGIN: List[Dict[str, Any]] = [
        {
            "tool": "front_man",
            "instantiation_index": 0,
        },
    ]

    # A tool call in langchain's form, as an AIMessage carries it.
    ACCOUNTANT_CALL: Dict[str, Any] = {
        "name": "Accountant",
        "args": {"running_cost": 0.0},
        "id": "toolu_1",
        "type": "tool_call",
    }
    # The same call in its wire form: id, name and args only.
    ACCOUNTANT_CALL_WIRE: Dict[str, Any] = {
        "id": "toolu_1",
        "name": "Accountant",
        "args": {"running_cost": 0.0},
    }

    def test_from_dict_drops_a_stand_alone_tool_result_for_chat_history(self) -> None:
        """
        A tool result with no tool_call_id, or an empty one, has no call to pair
        with and no model accepts it, so it is not restored for a chat history.
        """
        converter = BaseMessageDictionaryConverter()
        without_id: Dict[str, Any] = {
            "type": ChatMessageType.AGENT_TOOL_RESULT,
            "text": "tool says",
        }
        empty_id: Dict[str, Any] = {
            "type": ChatMessageType.AGENT_TOOL_RESULT,
            "text": "tool says",
            "tool_call_id": "",
        }

        self.assertIsNone(converter.from_dict(without_id))
        self.assertIsNone(converter.from_dict(empty_id))

    def test_to_dict_ai_tool_calls_exact_shape(self) -> None:
        """
        An AI message that only made a tool call carries its empty text and the
        call as id, name and args.
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        message: AIMessage = AIMessage(content="", tool_calls=[self.ACCOUNTANT_CALL])

        self.assertEqual(converter.to_dict(message), {
            "type": ChatMessageType.AI,
            "origin": self.ORIGIN,
            "text": "",
            "tool_calls": [self.ACCOUNTANT_CALL_WIRE],
        })

    def test_to_dict_tool_message_exact_shape(self) -> None:
        """
        A ToolMessage goes out as an AGENT_TOOL_RESULT that names the call it answers.
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        message: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="toolu_1")

        self.assertEqual(converter.to_dict(message), {
            "type": ChatMessageType.AGENT_TOOL_RESULT,
            "origin": self.ORIGIN,
            "text": "{'running_cost': 3.0}",
            "tool_call_id": "toolu_1",
        })

    def test_from_dict_round_trips_a_tool_call_and_its_result(self) -> None:
        """
        A tool-calling AI message and the ToolMessage answering it come back from
        their dictionaries with the call and the id that pairs them.
        """
        converter = BaseMessageDictionaryConverter()
        call: AIMessage = AIMessage(content="", tool_calls=[self.ACCOUNTANT_CALL])
        result: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="toolu_1")

        restored_call: BaseMessage = converter.from_dict(converter.to_dict(call))
        restored_result: BaseMessage = converter.from_dict(converter.to_dict(result))

        self.assertIsInstance(restored_call, AIMessage)
        self.assertEqual(restored_call.content, "")
        self.assertEqual(len(restored_call.tool_calls), 1)
        self.assertEqual(restored_call.tool_calls[0].get("id"), "toolu_1")
        self.assertEqual(restored_call.tool_calls[0].get("name"), "Accountant")
        self.assertEqual(restored_call.tool_calls[0].get("args"), {"running_cost": 0.0})
        self.assertIsInstance(restored_result, ToolMessage)
        self.assertEqual(restored_result.content, "{'running_cost': 3.0}")
        self.assertEqual(restored_result.tool_call_id, "toolu_1")

    def test_tool_result_error_status_round_trips(self) -> None:
        """
        A failed tool result goes out with tool_status "error" and comes back as a
        ToolMessage with that status; a successful one carries no tool_status.
        """
        converter = BaseMessageDictionaryConverter()
        failed: ToolMessage = ToolMessage(content="denied", tool_call_id="toolu_1", status="error")
        succeeded: ToolMessage = ToolMessage(content="3.0", tool_call_id="toolu_2")

        failed_dict: Dict[str, Any] = converter.to_dict(failed)
        succeeded_dict: Dict[str, Any] = converter.to_dict(succeeded)
        restored: ToolMessage = converter.from_dict(failed_dict)

        self.assertEqual(failed_dict.get("tool_status"), "error")
        self.assertNotIn("tool_status", succeeded_dict)
        self.assertEqual(restored.status, "error")
        self.assertEqual(converter.from_dict(succeeded_dict).status, "success")

    def test_from_dict_drops_a_call_only_message_whose_calls_are_all_malformed(self) -> None:
        """
        A call-only AI entry whose every call is rejected restores to nothing
        rather than to an empty assistant message, which providers reject.
        """
        converter = BaseMessageDictionaryConverter()
        chat_message: Dict[str, Any] = {
            "type": ChatMessageType.AI,
            "text": "",
            "tool_calls": [
                {
                    "id": "toolu_1",
                    "name": "",
                    "args": {},
                },
            ],
        }

        with self.assertLogs("BaseMessageDictionaryConverter", level="WARNING"):
            restored: BaseMessage = converter.from_dict(chat_message)

        self.assertIsNone(restored)

    def test_from_dict_skips_malformed_tool_calls(self) -> None:
        """
        A tool call without a string id and name, or with args that are not a
        dictionary, is left out with a warning; well-formed calls are kept, and
        missing args become an empty dictionary.
        """
        converter = BaseMessageDictionaryConverter()
        chat_message: Dict[str, Any] = {
            "type": ChatMessageType.AI,
            "text": "",
            "tool_calls": [
                {
                    "id": "",
                    "name": "lookup",
                    "args": {},
                },
                {
                    "id": "toolu_1",
                    "name": "lookup",
                    "args": "not a dictionary",
                },
                "junk",
                {
                    "id": "toolu_2",
                    "name": "lookup",
                },
            ],
        }

        with self.assertLogs("BaseMessageDictionaryConverter", level="WARNING") as logs:
            restored: BaseMessage = converter.from_dict(chat_message)

        self.assertEqual(len(logs.output), 3)
        # The warning names the call but never carries its arguments, which can hold secrets.
        self.assertIn("'toolu_1'", logs.output[1])
        self.assertNotIn("not a dictionary", logs.output[1])
        self.assertEqual(len(restored.tool_calls), 1)
        self.assertEqual(restored.tool_calls[0].get("id"), "toolu_2")
        self.assertEqual(restored.tool_calls[0].get("args"), {})

    def test_ai_message_from_dict_keeps_block_content_with_tool_calls(self) -> None:
        """
        Content handed in as a list of blocks is kept as given next to the
        restored tool calls, so a caller that rebuilds block content from the
        dictionary does not lose the calls.
        """
        converter = BaseMessageDictionaryConverter()
        blocks: List[Dict[str, Any]] = [
            {
                "type": "reasoning",
                "reasoning": "r",
            },
        ]
        chat_message: Dict[str, Any] = {
            "type": ChatMessageType.AI,
            "text": "",
            "tool_calls": [self.ACCOUNTANT_CALL_WIRE],
        }

        restored: AIMessage = converter.ai_message_from_dict(blocks, chat_message)

        self.assertEqual(restored.content, blocks)
        self.assertEqual(len(restored.tool_calls), 1)
        self.assertEqual(restored.tool_calls[0].get("id"), "toolu_1")

    def test_from_dict_ai_without_tool_calls_is_plain(self) -> None:
        """
        An AI dictionary with no tool_calls key, or an empty list, restores to a
        plain AIMessage with no tool calls.
        """
        converter = BaseMessageDictionaryConverter()
        without_key: Dict[str, Any] = {
            "type": ChatMessageType.AI,
            "text": "the answer",
        }
        with_empty_list: Dict[str, Any] = {
            "type": ChatMessageType.AI,
            "text": "the answer",
            "tool_calls": [],
        }

        plain: BaseMessage = converter.from_dict(without_key)
        empty: BaseMessage = converter.from_dict(with_empty_list)

        self.assertEqual(plain.tool_calls, [])
        self.assertEqual(empty.tool_calls, [])
