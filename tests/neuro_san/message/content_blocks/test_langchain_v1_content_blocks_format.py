
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
from langchain_core.messages.ai import AIMessageChunk
from typing_extensions import override

from neuro_san.message.content_blocks.langchain_v1_content_blocks_format import LangchainV1ContentBlocksFormat

from tests.neuro_san.message.content_fixtures import ContentFixtures


# pylint: disable=too-many-public-methods
class TestLangchainV1ContentBlocksFormat(TestCase):
    """
    Tests for the langchain_v1 content_blocks format: which values count as
    block content, how a message is viewed as blocks, which block lists are
    trivial, which inbound blocks survive a restore, and the blocks and
    metadata the format builds. Fixtures mirror real provider output
    shapes - see ContentFixtures.
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
        accepted: Dict[str, List[Dict[str, Any]]] = {
            "text": [
                {
                    "type": "text",
                    "text": "hi",
                },
            ],
            "reasoning then text": [
                {
                    "type": "reasoning",
                    "reasoning": "deep",
                },
                {
                    "type": "text",
                    "text": "hi",
                },
            ],
            "image": [
                {
                    "type": "image",
                    "base64": "AAAA",
                    "mime_type": "image/png",
                },
            ],
            "non_standard": [
                {
                    "type": "non_standard",
                    "value": {
                        "type": "redacted_thinking",
                        "data": "x",
                    },
                },
            ],
        }
        # Each list qualifies as block content.
        label: str = None
        value: List[Dict[str, Any]] = None
        for label, value in accepted.items():
            with self.subTest(case=label):
                self.assertTrue(self.blocks_format.is_block_list(value))

    def test_is_block_list_rejects_other_shapes(self) -> None:
        """
        Empty lists, non-lists, bare strings, blocks whose type is not a
        string, provider-native shapes, v0-era blocks and tool-call blocks
        do not qualify.
        """
        rejected: Dict[str, Any] = {
            "empty": [],
            "string": "text",
            "list of str": ["text"],
            "type is a list": [
                {
                    "type": [],
                    "text": "hi",
                },
            ],
            "type is a dict": [
                {
                    "type": {},
                    "text": "hi",
                },
            ],
            "native thinking": [
                {
                    "type": "thinking",
                    "thinking": "deep",
                },
            ],
            "v0 block": [
                {
                    "type": "image",
                    "source_type": "base64",
                    "data": "AAAA",
                },
            ],
            "tool call": [
                {
                    "type": "tool_call",
                    "name": "lookup",
                    "args": {},
                    "id": "call_1",
                },
            ],
            "mixed with non-dict": [
                {
                    "type": "text",
                    "text": "hi",
                },
                42,
            ],
        }
        # Each case is rejected.
        label: str = None
        value: Any = None
        for label, value in rejected.items():
            with self.subTest(case=label):
                self.assertFalse(self.blocks_format.is_block_list(value))

    def test_blocks_of_translates_anthropic_thinking(self) -> None:
        """
        Provider-native thinking standardizes to a reasoning block with the
        signature preserved in extras, so it can round-trip for multi-turn
        thinking plus tool use.
        """
        blocks: List[Dict[str, Any]] = self.blocks_format.blocks_of(ContentFixtures.anthropic_thinking_first())
        self.assertEqual(self.block_types(blocks), ["reasoning", "text"])
        self.assertEqual(blocks[0].get("reasoning"), "Let me reason this through.")
        self.assertEqual(blocks[0].get("extras").get("signature"), "sig-abc")

    def test_blocks_of_excludes_tool_call_blocks(self) -> None:
        """
        The content_blocks property merges .tool_calls into its view. Those
        blocks are not content and are left out, for complete messages and
        for chunks alike, so tool-calling traffic keeps its wire shape.
        """
        blocks: List[Dict[str, Any]] = self.blocks_format.blocks_of(ContentFixtures.anthropic_tool_use())
        self.assertEqual(self.block_types(blocks), ["text"])

        chunk: AIMessageChunk = AIMessageChunk(content=[
            {
                "type": "text",
                "text": "partial",
                "index": 0,
            },
            {
                "type": "tool_call_chunk",
                "name": "f",
                "args": '{"x"',
                "id": "c1",
                "index": 1,
            },
        ])
        self.assertEqual(self.block_types(self.blocks_format.blocks_of(chunk)), ["text"])

    def test_blocks_of_explodes_openai_reasoning_summary(self) -> None:
        """
        OpenAI Responses reasoning items standardize to reasoning blocks.
        """
        blocks: List[Dict[str, Any]] = self.blocks_format.blocks_of(ContentFixtures.openai_responses_reasoning())
        types: List[str] = self.block_types(blocks)
        self.assertIn("reasoning", types)
        self.assertIn("text", types)
        reasoning: List[Dict[str, Any]] = []
        # Collect the reasoning blocks.
        block: Dict[str, Any] = None
        for block in blocks:
            if block.get("type") == "reasoning":
                reasoning.append(block)
        self.assertEqual(reasoning[0].get("reasoning"), "thought one")

    def test_blocks_of_passes_standard_content_through(self) -> None:
        """
        Content that is already standard blocks, marked as such in its
        response_metadata, passes through untranslated: reasoning stays
        reasoning, not non_standard.
        """
        blocks: List[Dict[str, Any]] = self.blocks_format.blocks_of(ContentFixtures.v1_reasoning_blocks())
        self.assertEqual(self.block_types(blocks), ["reasoning", "text"])

    def test_is_trivial(self) -> None:
        """
        Exactly one text block whose other keys are empty is trivial; anything
        else is not. Empty annotations or extras do not count, and neither do
        the provider bookkeeping keys id and index: such messages are plain
        strings on today's wire, and the collapse deliberately drops those
        keys. Any other key with a value (an OpenAI Responses "phase") does
        count.
        """
        trivial: Dict[str, List[Dict[str, Any]]] = {
            "text only": [
                {
                    "type": "text",
                    "text": "hi",
                },
            ],
            "empty annotations and extras": [
                {
                    "type": "text",
                    "text": "hi",
                    "annotations": [],
                    "extras": {},
                },
            ],
            "none and empty string": [
                {
                    "type": "text",
                    "text": "hi",
                    "annotations": None,
                    "extras": "",
                },
            ],
            "provider id and index": [
                {
                    "type": "text",
                    "text": "hi",
                    "id": "msg_1",
                    "index": 0,
                },
            ],
        }
        # Each list says nothing beyond its text.
        label: str = None
        blocks: List[Dict[str, Any]] = None
        for label, blocks in trivial.items():
            with self.subTest(case=label):
                self.assertTrue(self.blocks_format.is_trivial(blocks))

        non_trivial: Dict[str, List[Dict[str, Any]]] = {
            "final answer phase": [
                {
                    "type": "text",
                    "text": "hi",
                    "phase": "final_answer",
                },
            ],
            "commentary phase": [
                {
                    "type": "text",
                    "text": "hi",
                    "phase": "commentary",
                },
            ],
            "empty list": [],
            "reasoning": [
                {
                    "type": "reasoning",
                    "reasoning": "r",
                },
            ],
            "two text blocks": [
                {
                    "type": "text",
                    "text": "a",
                },
                {
                    "type": "text",
                    "text": "b",
                },
            ],
            "citation": [
                {
                    "type": "text",
                    "text": "hi",
                    "annotations": [{"type": "citation"}],
                },
            ],
            "signature": [
                {
                    "type": "text",
                    "text": "hi",
                    "extras": {"signature": "s"},
                },
            ],
        }
        # Each list says more than its text.
        for label, blocks in non_trivial.items():
            with self.subTest(case=label):
                self.assertFalse(self.blocks_format.is_trivial(blocks))

    def test_is_empty_value(self) -> None:
        """
        None, "", [] and {} are empty; anything with content, and other
        types, are not.
        """
        self.assertTrue(LangchainV1ContentBlocksFormat.is_empty_value(None))
        self.assertTrue(LangchainV1ContentBlocksFormat.is_empty_value(""))
        self.assertTrue(LangchainV1ContentBlocksFormat.is_empty_value([]))
        self.assertTrue(LangchainV1ContentBlocksFormat.is_empty_value({}))
        self.assertFalse(LangchainV1ContentBlocksFormat.is_empty_value("final_answer"))
        self.assertFalse(LangchainV1ContentBlocksFormat.is_empty_value([{"type": "citation"}]))
        self.assertFalse(LangchainV1ContentBlocksFormat.is_empty_value({"signature": "s"}))
        self.assertFalse(LangchainV1ContentBlocksFormat.is_empty_value(0))
        self.assertFalse(LangchainV1ContentBlocksFormat.is_empty_value(False))

    def test_restore_blocks_keeps_replayable_blocks(self) -> None:
        """
        Text blocks with a text string keep every key, and reasoning blocks
        that carry anything stay. The kept blocks are the caller's own
        dictionaries, in order.
        """
        blocks: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": "the answer",
                "phase": "final_answer",
                "extras": {"k": "v"},
            },
            {
                "type": "text",
                "text": "",
            },
            {
                "type": "reasoning",
                "reasoning": "deep",
            },
            {
                "type": "reasoning",
                "id": "rs_1",
            },
            {
                "type": "reasoning",
                "extras": {"signature": "sig"},
            },
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
        blocks, non-dicts, non-string types and malformed blocks are all
        dropped.
        """
        dropped: Dict[str, Any] = {
            "tool_call": {
                "type": "tool_call",
                "name": "lookup",
                "args": {},
                "id": "call_1",
            },
            "tool_call_chunk": {
                "type": "tool_call_chunk",
                "name": "lookup",
                "args": "",
                "id": "c",
                "index": 0,
            },
            "invalid_tool_call": {
                "type": "invalid_tool_call",
                "name": "x",
                "args": "{",
                "id": "c",
                "error": "e",
            },
            "server_tool_call": {
                "type": "server_tool_call",
                "name": "web_search",
                "args": {},
                "id": "s",
            },
            "server_tool_result": {
                "type": "server_tool_result",
                "tool_call_id": "s",
                "output": [],
            },
            "non_standard": {
                "type": "non_standard",
                "value": {
                    "type": "redacted_thinking",
                    "data": "x",
                },
            },
            "native thinking": {
                "type": "thinking",
                "thinking": "deep",
                "signature": "sig",
            },
            "v0 block": {
                "type": "image",
                "source_type": "base64",
                "data": "AAAA",
            },
            "non-dict": "just a string",
            "type is a list": {
                "type": [],
                "text": "hi",
            },
            "type is a dict": {
                "type": {},
                "text": "hi",
            },
            "text without text": {"type": "text"},
            "text with non-str text": {
                "type": "text",
                "text": 42,
            },
            "empty reasoning": {"type": "reasoning"},
            "reasoning with empty parts": {
                "type": "reasoning",
                "reasoning": "",
                "id": "",
                "extras": {},
            },
            "image with payload": {
                "type": "image",
                "base64": "AAAA",
                "mime_type": "image/png",
            },
            "image without payload": {
                "type": "image",
                "mime_type": "image/png",
            },
            "file with url": {
                "type": "file",
                "url": "https://example.com/a.pdf",
            },
            "audio with file_id": {
                "type": "audio",
                "file_id": "file_1",
            },
            "text-plain with inline text": {
                "type": "text-plain",
                "mime_type": "text/plain",
                "text": "inline",
            },
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
            {
                "type": "tool_call",
                "name": "lookup",
                "args": {},
                "id": "call_1",
            },
            {
                "type": "reasoning",
                "reasoning": "deep",
            },
            {
                "type": "non_standard",
                "value": {"x": 1},
            },
            {
                "type": "text",
                "text": "the answer",
            },
        ]
        kept: List[Dict[str, Any]] = self.blocks_format.restore_blocks(blocks)
        self.assertEqual(self.block_types(kept), ["reasoning", "text"])

    def test_restore_blocks_holds_reasoning_back_for_chat_history(self) -> None:
        """
        Blocks bound for a model's chat history lose their reasoning blocks;
        everything else keeps its order and identity. Without the flag the
        reasoning blocks stay.
        """
        text: Dict[str, Any] = {
            "type": "text",
            "text": "a",
        }
        blocks: List[Dict[str, Any]] = [
            {
                "type": "reasoning",
                "reasoning": "deep",
            },
            text,
            {
                "type": "reasoning",
                "id": "rs_1",
            },
        ]
        remaining: List[Dict[str, Any]] = self.blocks_format.restore_blocks(blocks, for_chat_history=True)
        self.assertEqual(len(remaining), 1)
        self.assertIs(remaining[0], text)
        self.assertEqual(self.blocks_format.restore_blocks([], for_chat_history=True), [])
        self.assertEqual(self.block_types(self.blocks_format.restore_blocks(blocks)),
                         ["reasoning", "text", "reasoning"])

    def test_without_reasoning(self) -> None:
        """
        Reasoning blocks are left out; everything else keeps its order and identity.
        """
        text: Dict[str, Any] = {
            "type": "text",
            "text": "a",
        }
        blocks: List[Dict[str, Any]] = [
            {
                "type": "reasoning",
                "reasoning": "deep",
            },
            text,
            {
                "type": "reasoning",
                "id": "rs_1",
            },
        ]
        remaining: List[Dict[str, Any]] = self.blocks_format.without_reasoning(blocks)
        self.assertEqual(len(remaining), 1)
        self.assertIs(remaining[0], text)
        self.assertEqual(self.blocks_format.without_reasoning([]), [])

    def test_history_safe_text_references_data_blocks(self) -> None:
        """
        The assistant-history projection keeps text and replaces data blocks
        with a short reference - an image-only tool result must not become
        empty history. Strings in the list and text-plain inline text pass
        through.
        """
        self.assertEqual(self.blocks_format.history_safe_text(ContentFixtures.mcp_tool_content()),
                         "Here is the chart.[image attachment: image/png]")
        image_only: List[Dict[str, Any]] = [
            {
                "type": "image",
                "base64": "AAAA",
                "mime_type": "image/png",
            },
        ]
        self.assertEqual(self.blocks_format.history_safe_text(image_only), "[image attachment: image/png]")
        self.assertEqual(self.blocks_format.history_safe_text(["plain"]), "plain")
        inline_doc: List[Dict[str, Any]] = [
            {
                "type": "text-plain",
                "mime_type": "text/plain",
                "text": "inline doc",
            },
        ]
        self.assertEqual(self.blocks_format.history_safe_text(inline_doc), "inline doc")

    def test_text_block(self) -> None:
        """
        A text block is the type and the text, in that key order.
        """
        block: Dict[str, Any] = self.blocks_format.text_block("hi")
        expected: Dict[str, Any] = {
            "type": "text",
            "text": "hi",
        }
        self.assertEqual(block, expected)
        self.assertEqual(list(block.keys()), list(expected.keys()))

    def test_data_block(self) -> None:
        """
        The data-block type is chosen from the MIME prefix, anything else is
        a file, and text/plain gets its own block type. Keys keep their
        order so the wire shape stays the same.
        """
        cases: Dict[str, Dict[str, Any]] = {
            "image/png": {
                "type": "image",
                "base64": "aW1n",
                "mime_type": "image/png",
            },
            "audio/wav": {
                "type": "audio",
                "base64": "YXVk",
                "mime_type": "audio/wav",
            },
            "video/mp4": {
                "type": "video",
                "base64": "dmlk",
                "mime_type": "video/mp4",
            },
            "application/pdf": {
                "type": "file",
                "base64": "cGRm",
                "mime_type": "application/pdf",
            },
            "text/plain": {
                "type": "text-plain",
                "mime_type": "text/plain",
                "base64": "dHh0",
            },
        }
        # Each MIME type maps to its block shape.
        mime_type: str = None
        expected: Dict[str, Any] = None
        for mime_type, expected in cases.items():
            with self.subTest(mime_type=mime_type):
                block: Dict[str, Any] = self.blocks_format.data_block(mime_type, expected.get("base64"))
                self.assertEqual(block, expected)
                self.assertEqual(list(block.keys()), list(expected.keys()))

    def test_response_metadata_for(self) -> None:
        """
        The message's own metadata is copied and stamped with the output
        version; the original is untouched.
        """
        message: AIMessage = AIMessage(content="a", response_metadata={"model_provider": "openai"})
        stamped: Dict[str, Any] = self.blocks_format.response_metadata_for(message)
        expected: Dict[str, Any] = {
            "model_provider": "openai",
            "output_version": "v1",
        }
        self.assertEqual(stamped, expected)
        self.assertEqual(message.response_metadata, {"model_provider": "openai"})
        self.assertEqual(self.blocks_format.response_metadata_for(AIMessage(content="a")), {"output_version": "v1"})
        self.assertEqual(LangchainV1ContentBlocksFormat.OUTPUT_VERSION, "v1")

    def test_is_format_of(self) -> None:
        """
        Only a message whose response_metadata carries the v1 output version
        is recognized; a missing or different mark is not.
        """
        marked: AIMessage = AIMessage(content="a", response_metadata={"output_version": "v1"})
        self.assertTrue(self.blocks_format.is_format_of(marked))
        stamped: Dict[str, Any] = self.blocks_format.response_metadata_for(AIMessage(content="a"))
        self.assertTrue(self.blocks_format.is_format_of(AIMessage(content="a", response_metadata=stamped)))
        self.assertFalse(self.blocks_format.is_format_of(AIMessage(content="a")))
        other: AIMessage = AIMessage(content="a", response_metadata={"output_version": "v9"})
        self.assertFalse(self.blocks_format.is_format_of(other))

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
