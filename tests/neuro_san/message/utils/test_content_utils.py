
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

import json

from typing import Any
from typing import Dict
from typing import List

from unittest import TestCase

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.ai import AIMessageChunk

from neuro_san.message.content_blocks.content_blocks_format import ContentBlocksFormat
from neuro_san.message.content_blocks.content_blocks_format_registry import ContentBlocksFormatRegistry
from neuro_san.message.content_blocks.langchain_v1_content_blocks_format import LangchainV1ContentBlocksFormat
from neuro_san.message.utils.content_utils import ContentUtils

from tests.neuro_san.message.content_fixtures import ContentFixtures


# pylint: disable=too-many-public-methods
class TestContentUtils(TestCase):
    """
    Tests for ContentUtils, the single flatten/standardize/inspect policy
    for message content. Fixtures mirror real provider output shapes -
    see ContentFixtures.
    """

    @staticmethod
    def _block_types(blocks: List[Dict[str, Any]]) -> List[str]:
        """
        Collect the "type" value of each content block, in order.

        :param blocks: The standardized content blocks to inspect
        :return: The list of block type strings, one per block
        """
        types: List[str] = []
        # Collect the type of each block.
        block: Dict[str, Any] = None
        for block in blocks:
            types.append(block.get("type"))
        return types

    # --- flatten_to_text

    def test_flatten_plain_string_is_untouched(self):
        """
        Plain strings pass through exactly - including whitespace, which some
        call sites strip themselves and some must not.
        """
        self.assertEqual(ContentUtils.flatten_to_text(ContentFixtures.whitespace_text()), "  the answer  ")
        self.assertEqual(ContentUtils.flatten_to_text("hello"), "hello")

    def test_flatten_thinking_first_yields_answer_text(self):
        """
        An Anthropic thinking-first response must flatten to the answer text.
        (Today's first-block flatten yields "" for this shape.)
        """
        self.assertEqual(ContentUtils.flatten_to_text(ContentFixtures.anthropic_thinking_first()), "the answer")

    def test_flatten_concatenates_all_text_blocks(self):
        """
        Text blocks after the first must not be dropped.
        """
        content = [
            {"type": "text", "text": "part one, "},
            {"type": "reasoning", "reasoning": "hidden"},
            {"type": "text", "text": "part two"},
        ]
        self.assertEqual(ContentUtils.flatten_to_text(content), "part one, part two")

    def test_flatten_list_of_str_does_not_crash(self):
        """
        List-of-strings content is legal per the pydantic annotation and
        raises AttributeError in today's flatten.
        """
        self.assertEqual(ContentUtils.flatten_to_text(ContentFixtures.list_of_str()), "part one, part two")

    def test_flatten_empty_and_none(self):
        """
        Empty content shapes yield "" rather than crashing or yielding None.
        """
        self.assertEqual(ContentUtils.flatten_to_text(None), "")
        self.assertEqual(ContentUtils.flatten_to_text([]), "")
        self.assertEqual(ContentUtils.flatten_to_text(ContentFixtures.empty_list_content()), "")

    def test_flatten_ignores_non_text_blocks(self):
        """
        Data blocks contribute nothing to the text projection.
        """
        self.assertEqual(ContentUtils.flatten_to_text(ContentFixtures.mcp_tool_content()), "Here is the chart.")

    # --- is_empty_content

    def test_is_empty_content(self):
        """
        Whitespace-only strings, empty lists, and all-blank blocks are empty;
        any non-text block counts as content.
        """
        self.assertTrue(ContentUtils.is_empty_content("   "))
        self.assertTrue(ContentUtils.is_empty_content([]))
        self.assertTrue(ContentUtils.is_empty_content([{"type": "text", "text": " "}]))
        self.assertFalse(ContentUtils.is_empty_content("x"))
        self.assertFalse(ContentUtils.is_empty_content([{"type": "reasoning", "reasoning": "r"}]))
        self.assertFalse(ContentUtils.is_empty_content(ContentFixtures.mcp_tool_content()))

    # --- standard_blocks

    def test_standard_blocks_is_the_format_view(self) -> None:
        """
        standard_blocks is a funnel: the block view of the message in the
        format the message is in, made JSON-safe. Which blocks a provider
        shape becomes is the format's business and is tested with the format.
        """
        message: AIMessage = ContentFixtures.anthropic_thinking_first()
        default_format: ContentBlocksFormat = ContentBlocksFormatRegistry.get_default()
        blocks: List[Dict[str, Any]] = ContentUtils.standard_blocks(message)
        self.assertEqual(blocks, ContentUtils.to_json_safe(default_format.blocks_of(message)))
        self.assertEqual(self._block_types(blocks), ["reasoning", "text"])

    def test_standard_blocks_output_is_json_safe(self) -> None:
        """
        Bytes in block payloads become base64 strings so the wire path's
        to_json_safe (which nulls bytes) can never destroy them.
        """
        message = AIMessage(content=[
            {"type": "text", "text": "with bytes"},
            {"type": "image", "base64": b"raw-bytes", "mime_type": "image/png"},
        ])
        blocks: List[Dict[str, Any]] = ContentUtils.standard_blocks(message)
        json.dumps(blocks)
        image: Dict[str, Any] = None
        # Find the image block.
        block: Dict[str, Any] = None
        for block in blocks:
            if block.get("type") == "image":
                image = block
                break
        self.assertIsInstance(image.get("base64"), str)

    # --- normalize_content / normalize_message

    def test_normalize_content_keeps_plain_strings(self):
        """
        String content is untouched - including whitespace.
        """
        self.assertEqual(ContentUtils.normalize_content(ContentFixtures.whitespace_text()), "  the answer  ")

    def test_normalize_content_collapses_trivial_and_empty(self):
        """
        A tool-use turn (text + tool_use, tool_call blocks excluded) collapses
        to its plain text; empty-list content collapses to "".
        """
        self.assertEqual(ContentUtils.normalize_content(ContentFixtures.anthropic_tool_use()), "Let me look that up.")
        self.assertEqual(ContentUtils.normalize_content(ContentFixtures.empty_list_content()), "")

    def test_normalize_content_keeps_reasoning_blocks(self):
        """
        Thinking-bearing content normalizes to the standardized block list.
        """
        normalized = ContentUtils.normalize_content(ContentFixtures.anthropic_thinking_first())
        self.assertIsInstance(normalized, list)
        self.assertEqual(self._block_types(normalized), ["reasoning", "text"])

    def test_normalize_message_stamps_output_version(self):
        """
        THE regression test for the double-translation trap: a normalized
        message must carry output_version="v1" so a later content_blocks
        access (e.g. at wire-conversion time) passes the standard blocks
        through instead of wrapping them as non_standard.
        """
        normalized = ContentUtils.normalize_message(ContentFixtures.anthropic_thinking_first())
        self.assertEqual(normalized.response_metadata["output_version"], "v1")
        # Model provider metadata survives, and re-standardizing stays stable.
        self.assertEqual(normalized.response_metadata["model_provider"], "anthropic")
        again = ContentUtils.standard_blocks(normalized)
        self.assertEqual(self._block_types(again), ["reasoning", "text"])

    def test_normalize_message_returns_same_instance_for_plain_strings(self):
        """
        Text-only traffic must not even be copied - shape and identity stable.
        """
        message = ContentFixtures.whitespace_text()
        self.assertIs(ContentUtils.normalize_message(message), message)

    def test_normalize_message_preserves_message_class_and_tool_calls(self):
        """
        model_copy keeps the subclass and sibling fields (tool_calls,
        usage_metadata) intact.
        """
        message = ContentFixtures.anthropic_tool_use()
        normalized = ContentUtils.normalize_message(message)
        self.assertIsInstance(normalized, AIMessage)
        self.assertEqual(normalized.tool_calls, message.tool_calls)
        self.assertEqual(normalized.content, "Let me look that up.")

    # --- looks_like_blocks

    def test_looks_like_blocks(self):
        """
        Standard v1 block lists qualify; provider-native shapes, non-lists,
        empty lists and unknown types do not.
        """
        self.assertTrue(ContentUtils.looks_like_blocks(ContentFixtures.multimodal_human().content))
        self.assertTrue(ContentUtils.looks_like_blocks(ContentFixtures.mcp_tool_content()))
        self.assertFalse(ContentUtils.looks_like_blocks("text"))
        self.assertFalse(ContentUtils.looks_like_blocks([]))
        self.assertFalse(ContentUtils.looks_like_blocks([{"type": "thinking", "thinking": "native"}]))
        self.assertFalse(ContentUtils.looks_like_blocks(["just a string"]))
        # v0-era blocks (source_type marker) and tool-call blocks are not
        # standard v1 content and must not be accepted inbound.
        self.assertFalse(ContentUtils.looks_like_blocks(
            [{"type": "image", "source_type": "base64", "data": "aGk=", "mime_type": "image/png"}]))
        self.assertFalse(ContentUtils.looks_like_blocks(
            [{"type": "tool_call", "name": "f", "args": {}, "id": "c1"}]))

    # --- blocks_from_chat_message

    def test_blocks_from_chat_message_prefers_content_blocks(self):
        """
        A content_blocks wrapper in the langchain_v1 format wins over mime_data
        when both are present, and its blocks list is returned as-is.
        """
        chat_message = {
            "type": "HUMAN",
            "text": "caption",
            "content_blocks": {
                "format": LangchainV1ContentBlocksFormat.NAME,
                "blocks": [{"type": "text", "text": "from blocks"}],
            },
            "mime_data": [{"mime_type": "image/png", "mime_bytes": "AAAA"}],
        }
        blocks = ContentUtils.blocks_from_chat_message(chat_message)
        self.assertEqual(blocks, [{"type": "text", "text": "from blocks"}])

    def test_blocks_from_chat_message_empty_wrapper_falls_through(self) -> None:
        """
        A wrapper without blocks carries nothing, so mime_data is still mapped.
        Absent, null and [] are the same wrapper on the wire (proto3 JSON omits
        an empty repeated field), and with nothing to interpret the format is
        not checked.
        """
        expected: List[Dict[str, Any]] = [
            {
                "type": "image",
                "base64": "AAAA",
                "mime_type": "image/png",
            },
        ]
        empty_wrappers: List[Dict[str, Any]] = [
            {
                "format": LangchainV1ContentBlocksFormat.NAME,
                "blocks": [],
            },
            {"format": LangchainV1ContentBlocksFormat.NAME},
            {
                "format": LangchainV1ContentBlocksFormat.NAME,
                "blocks": None,
            },
            {
                "format": "somebody_elses_v2",
                "blocks": [],
            },
            {},
        ]
        for wrapper in empty_wrappers:
            with self.subTest(content_blocks=wrapper):
                chat_message = {
                    "type": "HUMAN",
                    "content_blocks": wrapper,
                    "mime_data": [{"mime_type": "image/png", "mime_bytes": "AAAA"}],
                }
                self.assertEqual(ContentUtils.blocks_from_chat_message(chat_message), expected)

    def test_blocks_from_chat_message_unknown_format_or_bare_list_fails_safe(self) -> None:
        """
        A wrapper whose format this code does not know, and a bare list of
        blocks (the shape from before the format tag), both yield None and do
        NOT fall through to mime_data.
        """
        mime_data = [{"mime_type": "image/png", "mime_bytes": "AAAA"}]
        unknown_format = {
            "type": "HUMAN",
            "content_blocks": {"format": "somebody_elses_v2", "blocks": [{"type": "text", "text": "hi"}]},
            "mime_data": mime_data,
        }
        self.assertIsNone(ContentUtils.blocks_from_chat_message(unknown_format))
        bare_list = {
            "type": "HUMAN",
            "content_blocks": [{"type": "text", "text": "hi"}],
            "mime_data": mime_data,
        }
        self.assertIsNone(ContentUtils.blocks_from_chat_message(bare_list))

    def test_blocks_from_chat_message_maps_mime_data(self) -> None:
        """
        The simple-client mime_data shape maps to a text block for the text
        followed by one data block per entry, in the default format. The
        shape of each block is tested with the format.
        """
        chat_message = {
            "type": "HUMAN",
            "text": "Describe this image.",
            "mime_data": [
                {
                    "mime_type": "image/png",
                    "mime_bytes": "aW1n",
                },
                {
                    "mime_type": "text/plain",
                    "mime_bytes": "dHh0",
                },
            ],
        }
        blocks: List[Dict[str, Any]] = ContentUtils.blocks_from_chat_message(chat_message)
        expected: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": "Describe this image.",
            },
            {
                "type": "image",
                "base64": "aW1n",
                "mime_type": "image/png",
            },
            {
                "type": "text-plain",
                "mime_type": "text/plain",
                "base64": "dHh0",
            },
        ]
        self.assertEqual(blocks, expected)

    def test_flatten_matches_langchain_text_for_non_string_text_values(self):
        """
        A text block whose "text" value is not a string contributes nothing -
        exactly like langchain's own BaseMessage.text (never the literal
        "None").
        """
        content = [{"type": "text", "text": None}, {"type": "text", "text": 5}]
        message = AIMessage(content=content)
        self.assertEqual(ContentUtils.flatten_to_text(message), "")
        self.assertEqual(ContentUtils.flatten_to_text(message), str(message.text))
        self.assertTrue(ContentUtils.is_empty_content(message))

    def test_normalize_content_collapses_list_of_str(self):
        """
        List-of-strings content has no block structure to preserve - it
        collapses to the concatenated text, not a multi-text-block list.
        """
        self.assertEqual(ContentUtils.normalize_content(ContentFixtures.list_of_str()), "part one, part two")

    def test_normalize_message_is_idempotent(self):
        """
        Applying normalize_message twice yields the same content and metadata
        as applying it once (the v1 stamp prevents re-translation).
        """
        once = ContentUtils.normalize_message(ContentFixtures.anthropic_thinking_first())
        twice = ContentUtils.normalize_message(once)
        self.assertEqual(twice.content, once.content)
        self.assertEqual(twice.response_metadata, once.response_metadata)

    def test_utils_handle_message_chunks(self) -> None:
        """
        Chunk messages do not crash the text projection.
        """
        chunk = AIMessageChunk(content=[
            {"type": "text", "text": "partial", "index": 0},
            {"type": "tool_call_chunk", "name": "f", "args": '{"x"', "id": "c1", "index": 1},
        ])
        self.assertEqual(ContentUtils.flatten_to_text(chunk), "partial")

    def test_wrap_content_blocks(self) -> None:
        """
        The wire wrapper is the format tag plus the blocks list, as-is.
        """
        blocks = [{"type": "text", "text": "hi"}]
        self.assertEqual(ContentUtils.wrap_content_blocks(blocks), {"format": "langchain_v1", "blocks": blocks})

    def test_wrap_content_blocks_names_the_given_format(self) -> None:
        """
        The wrapper is named after the format passed in, and after the
        default format when none is.
        """
        blocks: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": "a",
            },
        ]
        default_format: ContentBlocksFormat = ContentBlocksFormatRegistry.get_default()
        named: Dict[str, Any] = ContentUtils.wrap_content_blocks(blocks, default_format)
        self.assertEqual(named.get("format"), default_format.get_name())
        self.assertEqual(ContentUtils.wrap_content_blocks(blocks), named)

    def test_unwrap_content_blocks(self) -> None:
        """
        unwrap returns the blocks of a langchain_v1 wrapper as-is, an empty
        list for an empty wrapper whatever its format, and None for anything
        that is not a wrapper this code knows.
        """
        blocks = [{"type": "text", "text": "hi"}]
        self.assertIs(ContentUtils.unwrap_content_blocks({"format": "langchain_v1", "blocks": blocks}), blocks)
        self.assertEqual(ContentUtils.unwrap_content_blocks({"format": "langchain_v1", "blocks": []}), [])
        self.assertEqual(ContentUtils.unwrap_content_blocks({"format": "langchain_v1"}), [])
        self.assertEqual(ContentUtils.unwrap_content_blocks({"format": "somebody_elses_v2", "blocks": []}), [])
        self.assertEqual(ContentUtils.unwrap_content_blocks({}), [])
        self.assertIsNone(ContentUtils.unwrap_content_blocks({"format": "somebody_elses_v2", "blocks": blocks}))
        self.assertIsNone(ContentUtils.unwrap_content_blocks({"blocks": blocks}))
        self.assertIsNone(ContentUtils.unwrap_content_blocks({"format": "langchain_v1", "blocks": 42}))
        self.assertIsNone(ContentUtils.unwrap_content_blocks(blocks))
        self.assertIsNone(ContentUtils.unwrap_content_blocks(42))

    def test_history_safe_text_references_data_blocks(self) -> None:
        """
        List content goes through the default format's history projection,
        which replaces data blocks with a short reference. Plain strings and
        None do not reach the format and pass through as text.
        """
        self.assertEqual(ContentUtils.history_safe_text(ContentFixtures.mcp_tool_content()),
                         "Here is the chart.[image attachment: image/png]")
        self.assertEqual(ContentUtils.history_safe_text("plain"), "plain")
        self.assertEqual(ContentUtils.history_safe_text(None), "")
        self.assertEqual(ContentUtils.history_safe_text(AIMessage(content="plain")), "plain")

    def test_blocks_from_chat_message_text_only_and_malformed(self):
        """
        Text-only messages yield None (callers keep today's path), and
        malformed mime_data yields None (callers fall back to text).
        """
        self.assertIsNone(ContentUtils.blocks_from_chat_message(None))
        self.assertIsNone(ContentUtils.blocks_from_chat_message({"type": "HUMAN", "text": "hi"}))
        self.assertIsNone(ContentUtils.blocks_from_chat_message(
            {"type": "HUMAN", "text": "hi", "mime_data": []}))
        # Raw bytes / missing fields are malformed: base64 strings only.
        self.assertIsNone(ContentUtils.blocks_from_chat_message(
            {"type": "HUMAN", "mime_data": [{"mime_type": "image/png", "mime_bytes": b"raw"}]}))
        self.assertIsNone(ContentUtils.blocks_from_chat_message(
            {"type": "HUMAN", "mime_data": [{"mime_type": "image/png"}]}))
        self.assertIsNone(ContentUtils.blocks_from_chat_message(
            {"type": "HUMAN", "mime_data": [{"mime_bytes": "AAAA"}]}))

    def test_blocks_from_chat_message_malformed_content_blocks_fails_safe(self):
        """
        A present-but-invalid content_blocks value yields None - it must NOT
        fall through to the mime_data mapping (fail safe to text-only).
        """
        chat_message = {
            "type": "HUMAN",
            "text": "caption",
            "content_blocks": {
                "format": LangchainV1ContentBlocksFormat.NAME,
                "blocks": [{"type": "bogus-type", "x": 1}],
            },
            "mime_data": [{"mime_type": "image/png", "mime_bytes": "AAAA"}],
        }
        self.assertIsNone(ContentUtils.blocks_from_chat_message(chat_message))

    # --- to_json_safe

    def test_to_json_safe_makes_payloads_json_safe(self) -> None:
        """
        Bytes payloads become base64 strings and str items pass through, so
        the result can be serialized; the input list is not mutated.
        """
        blocks = [
            {"type": "text", "text": "chart"},
            {"type": "image", "base64": b"raw", "mime_type": "image/png"},
            "plain",
        ]
        safe = ContentUtils.to_json_safe(blocks)
        self.assertEqual(safe[1]["base64"], "cmF3")
        self.assertEqual(safe[2], "plain")
        json.dumps(safe)
        self.assertEqual(blocks[1]["base64"], b"raw")

    # --- restorable_blocks

    def test_content_blocks_format(self) -> None:
        """
        A wrapper names its format; anything else, an unknown name included,
        names none.
        """
        wrapper: Dict[str, Any] = {
            "format": LangchainV1ContentBlocksFormat.NAME,
            "blocks": [],
        }
        self.assertIs(ContentUtils.content_blocks_format(wrapper), ContentBlocksFormatRegistry.get_default())
        unknown: Dict[str, Any] = {
            "format": "somebody_elses_v2",
            "blocks": [],
        }
        self.assertIsNone(ContentUtils.content_blocks_format(unknown))
        self.assertIsNone(ContentUtils.content_blocks_format({"blocks": []}))
        bare_list: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": "hi",
            },
        ]
        self.assertIsNone(ContentUtils.content_blocks_format(bare_list))
        self.assertIsNone(ContentUtils.content_blocks_format(None))

    def test_restorable_blocks_restores_reasoning_and_text(self) -> None:
        """
        A langchain_v1 wrapper whose blocks say more than the text restores
        to those same block dictionaries, an OpenAI "phase" included.
        """
        blocks = [
            {
                "type": "reasoning",
                "reasoning": "deep",
                "extras": {"signature": "sig"},
            },
            {
                "type": "text",
                "text": "the answer",
                "phase": "final_answer",
            },
        ]
        chat_message = {
            "type": "AI",
            "text": "the answer",
            "content_blocks": ContentUtils.wrap_content_blocks(blocks),
        }
        restored: List[Dict[str, Any]] = ContentUtils.restorable_blocks(chat_message)
        self.assertEqual(restored, blocks)
        self.assertIs(restored[0], blocks[0])
        self.assertIs(restored[1], blocks[1])
        self.assertEqual(restored[1].get("phase"), "final_answer")

    def test_restorable_blocks_keeps_reasoning_only_content(self) -> None:
        """
        A reasoning-only message has no text to lose, so its block stays.
        """
        blocks = [
            {
                "type": "reasoning",
                "reasoning": "deep",
            },
        ]
        chat_message = {
            "type": "AI",
            "text": "",
            "content_blocks": ContentUtils.wrap_content_blocks(blocks),
        }
        self.assertEqual(ContentUtils.restorable_blocks(chat_message), blocks)

    def test_restorable_blocks_falls_back_to_text(self) -> None:
        """
        None means "keep the text as content": no wrapper, an unknown format,
        a bare list, an empty wrapper, nothing left after the restore, blocks
        that only repeat the text, and blocks whose text is not the message's
        text, whether lost, shortened or changed.
        """
        text_block = {
            "type": "text",
            "text": "the answer",
        }
        tool_call = {
            "type": "tool_call",
            "name": "lookup",
            "args": {},
            "id": "call_1",
        }
        cases: Dict[str, Dict[str, Any]] = {
            "no wrapper": {
                "type": "AI",
                "text": "the answer",
            },
            "unknown format": {
                "type": "AI",
                "text": "the answer",
                "content_blocks": {
                    "format": "somebody_elses_v2",
                    "blocks": [text_block],
                },
            },
            "bare list": {
                "type": "AI",
                "text": "the answer",
                "content_blocks": [text_block],
            },
            "empty wrapper": {
                "type": "AI",
                "text": "the answer",
                "content_blocks": ContentUtils.wrap_content_blocks([]),
            },
            "only dropped blocks": {
                "type": "AI",
                "text": "the answer",
                "content_blocks": ContentUtils.wrap_content_blocks([tool_call]),
            },
            "lone text block": {
                "type": "AI",
                "text": "the answer",
                "content_blocks": ContentUtils.wrap_content_blocks([text_block]),
            },
            "tool call plus text": {
                "type": "AI",
                "text": "the answer",
                "content_blocks": ContentUtils.wrap_content_blocks([tool_call, text_block]),
            },
            "blocks lost the text": {
                "type": "AI",
                "text": "the answer",
                "content_blocks": ContentUtils.wrap_content_blocks([
                    {
                        "type": "reasoning",
                        "reasoning": "deep",
                    },
                ]),
            },
            "blocks shortened the text": {
                "type": "AI",
                "text": "hello world",
                "content_blocks": ContentUtils.wrap_content_blocks([
                    {
                        "type": "text",
                        "text": "hello",
                        "phase": "final_answer",
                    },
                ]),
            },
            "blocks changed the text": {
                "type": "AI",
                "text": "the answer",
                "content_blocks": ContentUtils.wrap_content_blocks([
                    {
                        "type": "text",
                        "text": "another answer",
                        "phase": "final_answer",
                    },
                ]),
            },
            "none": None,
        }
        # Each case falls back to the text.
        label: str = None
        chat_message: Dict[str, Any] = None
        for label, chat_message in cases.items():
            with self.subTest(case=label):
                self.assertIsNone(ContentUtils.restorable_blocks(chat_message))

    def test_restorable_blocks_holds_reasoning_back_for_chat_history(self) -> None:
        """
        A message bound for chat history loses its reasoning blocks. What is
        left follows the usual rules: a text block with a phase is kept, a
        plain text block that repeats the text is not, and nothing at all
        means the text stays.
        """
        reasoning = {
            "type": "reasoning",
            "reasoning": "deep",
            "extras": {"signature": "sig"},
        }
        phased = {
            "type": "text",
            "text": "the answer",
            "phase": "final_answer",
        }
        plain = {
            "type": "text",
            "text": "the answer",
        }

        with_phase = {
            "type": "AI",
            "text": "the answer",
            "content_blocks": ContentUtils.wrap_content_blocks([reasoning, phased]),
        }
        self.assertEqual(ContentUtils.restorable_blocks(with_phase, for_chat_history=True), [phased])
        self.assertEqual(ContentUtils.restorable_blocks(with_phase), [reasoning, phased])

        with_plain = {
            "type": "AI",
            "text": "the answer",
            "content_blocks": ContentUtils.wrap_content_blocks([reasoning, plain]),
        }
        self.assertIsNone(ContentUtils.restorable_blocks(with_plain, for_chat_history=True))

        reasoning_only = {
            "type": "AI",
            "text": "",
            "content_blocks": ContentUtils.wrap_content_blocks([reasoning]),
        }
        self.assertIsNone(ContentUtils.restorable_blocks(reasoning_only, for_chat_history=True))

    def test_restorable_blocks_drops_attachments(self) -> None:
        """
        Data blocks are not sent back to a model yet, so they are dropped.
        A text block plus an attachment leaves only the text, which the
        message already has, and an attachment-only message keeps its text.
        """
        with_text = [
            {
                "type": "text",
                "text": "see",
            },
            {
                "type": "image",
                "base64": "aW1hZ2UtYnl0ZXM=",
                "mime_type": "image/png",
            },
        ]
        chat_message = {
            "type": "HUMAN",
            "text": "see",
            "content_blocks": ContentUtils.wrap_content_blocks(with_text),
        }
        self.assertIsNone(ContentUtils.restorable_blocks(chat_message))

        attachment_only = [
            {
                "type": "image",
                "base64": "aW1hZ2UtYnl0ZXM=",
                "mime_type": "image/png",
            },
        ]
        chat_message = {
            "type": "HUMAN",
            "text": "",
            "content_blocks": ContentUtils.wrap_content_blocks(attachment_only),
        }
        self.assertIsNone(ContentUtils.restorable_blocks(chat_message))

        with_reasoning = [
            {
                "type": "reasoning",
                "reasoning": "deep",
            },
            {
                "type": "text",
                "text": "see",
            },
            {
                "type": "image",
                "base64": "aW1hZ2UtYnl0ZXM=",
                "mime_type": "image/png",
            },
        ]
        chat_message = {
            "type": "AI",
            "text": "see",
            "content_blocks": ContentUtils.wrap_content_blocks(with_reasoning),
        }
        restored: List[Dict[str, Any]] = ContentUtils.restorable_blocks(chat_message)
        self.assertEqual(restored, with_reasoning[:2])
        self.assertNotIn("aW1hZ2UtYnl0ZXM=", json.dumps(restored))
