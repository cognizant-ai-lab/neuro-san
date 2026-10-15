
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

from typing_extensions import override

from neuro_san.message.content_blocks.langchain_v1_content_blocks_format import LangchainV1ContentBlocksFormat


class TestLangchainV1ContentBlocksFormat(TestCase):
    """
    Tests for the langchain_v1 content_blocks format: which values count as
    block content, and which inbound blocks survive a restore.
    """

    @override
    def setUp(self) -> None:
        """
        Create the format under test.
        """
        self.blocks_format: LangchainV1ContentBlocksFormat = LangchainV1ContentBlocksFormat()

    def test_get_name(self) -> None:
        """
        The format is named by its wire value.
        """
        self.assertEqual(self.blocks_format.get_name(), "langchain_v1")
        self.assertEqual(LangchainV1ContentBlocksFormat.NAME, "langchain_v1")

    def test_is_block_list_accepts_standard_content(self) -> None:
        """
        Non-empty lists of standard content blocks qualify, data blocks included.
        """
        accepted: List[List[Dict[str, Any]]] = [
            [{"type": "text", "text": "hi"}],
            [{"type": "reasoning", "reasoning": "deep"}, {"type": "text", "text": "hi"}],
            [{"type": "image", "base64": "AAAA", "mime_type": "image/png"}],
            [{"type": "non_standard", "value": {"type": "redacted_thinking", "data": "x"}}],
        ]
        # Each list qualifies as block content.
        value: List[Dict[str, Any]] = None
        for value in accepted:
            with self.subTest(types=str(self.block_types(value))):
                self.assertTrue(self.blocks_format.is_block_list(value))

    def test_is_block_list_rejects_other_shapes(self) -> None:
        """
        Empty lists, non-lists, bare strings, provider-native shapes, v0-era
        blocks and tool-call blocks do not qualify.
        """
        rejected: Dict[str, Any] = {
            "empty": [],
            "string": "text",
            "list of str": ["text"],
            "native thinking": [{"type": "thinking", "thinking": "deep"}],
            "v0 block": [{"type": "image", "source_type": "base64", "data": "AAAA"}],
            "tool call": [{"type": "tool_call", "name": "lookup", "args": {}, "id": "call_1"}],
            "mixed with non-dict": [{"type": "text", "text": "hi"}, 42],
        }
        # Each case is rejected.
        label: str = None
        value: Any = None
        for label, value in rejected.items():
            with self.subTest(case=label):
                self.assertFalse(self.blocks_format.is_block_list(value))

    def test_restore_blocks_keeps_replayable_blocks(self) -> None:
        """
        Text blocks with a text string keep every key, and reasoning blocks
        that carry anything stay. The kept blocks are the caller's own
        dictionaries, in order.
        """
        blocks: List[Dict[str, Any]] = [
            {"type": "text", "text": "the answer", "phase": "final_answer", "extras": {"k": "v"}},
            {"type": "text", "text": ""},
            {"type": "reasoning", "reasoning": "deep"},
            {"type": "reasoning", "id": "rs_1"},
            {"type": "reasoning", "extras": {"signature": "sig"}},
        ]
        kept: List[Dict[str, Any]] = self.blocks_format.restore_blocks(blocks)
        self.assertEqual(len(kept), len(blocks))
        # Each kept block is the dictionary passed in, at the same position.
        index: int = 0
        block: Dict[str, Any] = None
        for index, block in enumerate(blocks):
            self.assertIs(kept[index], block)

    def test_restore_blocks_drops_what_a_model_cannot_take(self) -> None:
        """
        Tool-call blocks, server-tool records, non_standard blocks, data
        blocks with or without a payload, provider-native shapes, v0-era
        blocks, non-dicts and malformed blocks are all dropped.
        """
        dropped: Dict[str, Any] = {
            "tool_call": {"type": "tool_call", "name": "lookup", "args": {}, "id": "call_1"},
            "tool_call_chunk": {"type": "tool_call_chunk", "name": "lookup", "args": "", "id": "c", "index": 0},
            "invalid_tool_call": {"type": "invalid_tool_call", "name": "x", "args": "{", "id": "c", "error": "e"},
            "server_tool_call": {"type": "server_tool_call", "name": "web_search", "args": {}, "id": "s"},
            "server_tool_result": {"type": "server_tool_result", "tool_call_id": "s", "output": []},
            "non_standard": {"type": "non_standard", "value": {"type": "redacted_thinking", "data": "x"}},
            "native thinking": {"type": "thinking", "thinking": "deep", "signature": "sig"},
            "v0 block": {"type": "image", "source_type": "base64", "data": "AAAA"},
            "non-dict": "just a string",
            "text without text": {"type": "text"},
            "text with non-str text": {"type": "text", "text": 42},
            "empty reasoning": {"type": "reasoning"},
            "reasoning with empty parts": {"type": "reasoning", "reasoning": "", "id": "", "extras": {}},
            "image with payload": {"type": "image", "base64": "AAAA", "mime_type": "image/png"},
            "image without payload": {"type": "image", "mime_type": "image/png"},
            "file with url": {"type": "file", "url": "https://example.com/a.pdf"},
            "audio with file_id": {"type": "audio", "file_id": "file_1"},
            "text-plain with inline text": {"type": "text-plain", "mime_type": "text/plain", "text": "inline"},
        }
        # Each block is dropped on its own.
        label: str = None
        block: Any = None
        for label, block in dropped.items():
            with self.subTest(case=label):
                self.assertEqual(self.blocks_format.restore_blocks([block]), [])

    def test_restore_blocks_keeps_order_of_survivors(self) -> None:
        """
        Dropping blocks does not reorder the survivors.
        """
        blocks: List[Dict[str, Any]] = [
            {"type": "tool_call", "name": "lookup", "args": {}, "id": "call_1"},
            {"type": "reasoning", "reasoning": "deep"},
            {"type": "non_standard", "value": {"x": 1}},
            {"type": "text", "text": "the answer"},
        ]
        kept: List[Dict[str, Any]] = self.blocks_format.restore_blocks(blocks)
        self.assertEqual(self.block_types(kept), ["reasoning", "text"])

    @staticmethod
    def block_types(blocks: List[Dict[str, Any]]) -> List[str]:
        """
        List the block types in order.

        :param blocks: A list of content blocks
        :return: The "type" of each block, in order
        """
        types: List[str] = []
        # Collect the type of each block.
        block: Dict[str, Any] = None
        for block in blocks:
            types.append(block.get("type"))
        return types
