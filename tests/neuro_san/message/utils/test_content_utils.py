
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

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.ai import AIMessageChunk

from neuro_san.message.utils.content_utils import ContentUtils

from tests.neuro_san.message.content_fixtures import ContentFixtures


# pylint: disable=too-many-public-methods
class TestContentUtils:
    """
    Tests for ContentUtils, the single flatten/standardize/inspect policy
    for message content. Fixtures mirror real provider output shapes -
    see ContentFixtures.
    """

    # --- flatten_to_text

    def test_flatten_plain_string_is_untouched(self):
        """
        Plain strings pass through exactly - including whitespace, which some
        call sites strip themselves and some must not.
        """
        assert ContentUtils.flatten_to_text(ContentFixtures.whitespace_text()) == "  the answer  "
        assert ContentUtils.flatten_to_text("hello") == "hello"

    def test_flatten_thinking_first_yields_answer_text(self):
        """
        An Anthropic thinking-first response must flatten to the answer text.
        (Today's first-block flatten yields "" for this shape.)
        """
        assert ContentUtils.flatten_to_text(ContentFixtures.anthropic_thinking_first()) == "the answer"

    def test_flatten_concatenates_all_text_blocks(self):
        """
        Text blocks after the first must not be dropped.
        """
        content = [
            {"type": "text", "text": "part one, "},
            {"type": "reasoning", "reasoning": "hidden"},
            {"type": "text", "text": "part two"},
        ]
        assert ContentUtils.flatten_to_text(content) == "part one, part two"

    def test_flatten_list_of_str_does_not_crash(self):
        """
        List-of-strings content is legal per the pydantic annotation and
        raises AttributeError in today's flatten.
        """
        assert ContentUtils.flatten_to_text(ContentFixtures.list_of_str()) == "part one, part two"

    def test_flatten_empty_and_none(self):
        """
        Empty content shapes yield "" rather than crashing or yielding None.
        """
        assert ContentUtils.flatten_to_text(None) == ""
        assert ContentUtils.flatten_to_text([]) == ""
        assert ContentUtils.flatten_to_text(ContentFixtures.empty_list_content()) == ""

    def test_flatten_ignores_non_text_blocks(self):
        """
        Data blocks contribute nothing to the text projection.
        """
        assert ContentUtils.flatten_to_text(ContentFixtures.mcp_tool_content()) == "Here is the chart."

    # --- is_empty_content

    def test_is_empty_content(self):
        """
        Whitespace-only strings, empty lists, and all-blank blocks are empty;
        any non-text block counts as content.
        """
        assert ContentUtils.is_empty_content("   ")
        assert ContentUtils.is_empty_content([])
        assert ContentUtils.is_empty_content([{"type": "text", "text": " "}])
        assert not ContentUtils.is_empty_content("x")
        assert not ContentUtils.is_empty_content([{"type": "reasoning", "reasoning": "r"}])
        assert not ContentUtils.is_empty_content(ContentFixtures.mcp_tool_content())

    # --- standard_blocks

    def test_standard_blocks_translates_anthropic_thinking(self):
        """
        Provider-native thinking must standardize to a reasoning block with
        the signature preserved in extras (it must round-trip for multi-turn
        thinking + tool use).
        """
        blocks = ContentUtils.standard_blocks(ContentFixtures.anthropic_thinking_first())
        assert [block["type"] for block in blocks] == ["reasoning", "text"]
        assert blocks[0]["reasoning"] == "Let me reason this through."
        assert blocks[0]["extras"]["signature"] == "sig-abc"

    def test_standard_blocks_excludes_tool_call_blocks(self):
        """
        The content_blocks property merges .tool_calls into the view; those
        must be excluded or every existing Anthropic tool-calling deployment
        would start emitting content_blocks in Phase 2 (parity break).
        """
        blocks = ContentUtils.standard_blocks(ContentFixtures.anthropic_tool_use())
        assert [block["type"] for block in blocks] == ["text"]

    def test_standard_blocks_explodes_openai_reasoning_summary(self):
        """
        OpenAI Responses reasoning items standardize to reasoning blocks.
        """
        blocks = ContentUtils.standard_blocks(ContentFixtures.openai_responses_reasoning())
        types = [block["type"] for block in blocks]
        assert "reasoning" in types
        assert "text" in types
        reasoning = [block for block in blocks if block["type"] == "reasoning"]
        assert reasoning[0].get("reasoning") == "thought one"

    def test_standard_blocks_passes_v1_content_through(self):
        """
        Content already in v1 form (output_version="v1") must pass through
        untranslated - reasoning stays reasoning, not non_standard.
        """
        blocks = ContentUtils.standard_blocks(ContentFixtures.v1_reasoning_blocks())
        assert [block["type"] for block in blocks] == ["reasoning", "text"]

    def test_standard_blocks_output_is_json_safe(self):
        """
        Bytes in block payloads become base64 strings so the wire path's
        to_json_safe (which nulls bytes) can never destroy them.
        """
        message = AIMessage(content=[
            {"type": "text", "text": "with bytes"},
            {"type": "image", "base64": b"raw-bytes", "mime_type": "image/png"},
        ])
        blocks = ContentUtils.standard_blocks(message)
        json.dumps(blocks)
        image = [block for block in blocks if block.get("type") == "image"][0]
        assert isinstance(image["base64"], str)

    # --- is_trivial

    def test_is_trivial(self):
        """
        Exactly one text block with no annotations/extras is trivial;
        anything else is not.
        """
        assert ContentUtils.is_trivial([{"type": "text", "text": "hi"}])
        assert not ContentUtils.is_trivial([])
        assert not ContentUtils.is_trivial([{"type": "reasoning", "reasoning": "r"}])
        assert not ContentUtils.is_trivial([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
        assert not ContentUtils.is_trivial([{"type": "text", "text": "hi", "annotations": [{"type": "citation"}]}])
        assert not ContentUtils.is_trivial([{"type": "text", "text": "hi", "extras": {"signature": "s"}}])

    # --- normalize_content / normalize_message

    def test_normalize_content_keeps_plain_strings(self):
        """
        String content is untouched - including whitespace.
        """
        assert ContentUtils.normalize_content(ContentFixtures.whitespace_text()) == "  the answer  "

    def test_normalize_content_collapses_trivial_and_empty(self):
        """
        A tool-use turn (text + tool_use, tool_call blocks excluded) collapses
        to its plain text; empty-list content collapses to "".
        """
        assert ContentUtils.normalize_content(ContentFixtures.anthropic_tool_use()) == "Let me look that up."
        assert ContentUtils.normalize_content(ContentFixtures.empty_list_content()) == ""

    def test_normalize_content_keeps_reasoning_blocks(self):
        """
        Thinking-bearing content normalizes to the standardized block list.
        """
        normalized = ContentUtils.normalize_content(ContentFixtures.anthropic_thinking_first())
        assert isinstance(normalized, list)
        assert [block["type"] for block in normalized] == ["reasoning", "text"]

    def test_normalize_message_stamps_output_version(self):
        """
        THE regression test for the double-translation trap: a normalized
        message must carry output_version="v1" so a later content_blocks
        access (e.g. at wire-conversion time) passes the standard blocks
        through instead of wrapping them as non_standard.
        """
        normalized = ContentUtils.normalize_message(ContentFixtures.anthropic_thinking_first())
        assert normalized.response_metadata["output_version"] == "v1"
        # Model provider metadata survives, and re-standardizing stays stable.
        assert normalized.response_metadata["model_provider"] == "anthropic"
        again = ContentUtils.standard_blocks(normalized)
        assert [block["type"] for block in again] == ["reasoning", "text"]

    def test_normalize_message_returns_same_instance_for_plain_strings(self):
        """
        Text-only traffic must not even be copied - shape and identity stable.
        """
        message = ContentFixtures.whitespace_text()
        assert ContentUtils.normalize_message(message) is message

    def test_normalize_message_preserves_message_class_and_tool_calls(self):
        """
        model_copy keeps the subclass and sibling fields (tool_calls,
        usage_metadata) intact.
        """
        message = ContentFixtures.anthropic_tool_use()
        normalized = ContentUtils.normalize_message(message)
        assert isinstance(normalized, AIMessage)
        assert normalized.tool_calls == message.tool_calls
        assert normalized.content == "Let me look that up."

    # --- looks_like_blocks

    def test_looks_like_blocks(self):
        """
        Standard v1 block lists qualify; provider-native shapes, non-lists,
        empty lists and unknown types do not.
        """
        assert ContentUtils.looks_like_blocks(ContentFixtures.multimodal_human().content)
        assert ContentUtils.looks_like_blocks(ContentFixtures.mcp_tool_content())
        assert not ContentUtils.looks_like_blocks("text")
        assert not ContentUtils.looks_like_blocks([])
        assert not ContentUtils.looks_like_blocks([{"type": "thinking", "thinking": "native"}])
        assert not ContentUtils.looks_like_blocks(["just a string"])
        # v0-era blocks (source_type marker) and tool-call blocks are not
        # standard v1 content and must not be accepted inbound.
        assert not ContentUtils.looks_like_blocks(
            [{"type": "image", "source_type": "base64", "data": "aGk=", "mime_type": "image/png"}])
        assert not ContentUtils.looks_like_blocks(
            [{"type": "tool_call", "name": "f", "args": {}, "id": "c1"}])

    # --- blocks_from_chat_message

    def test_blocks_from_chat_message_prefers_content_blocks(self):
        """
        content_blocks wins over mime_data when both are present.
        """
        chat_message = {
            "type": "HUMAN",
            "text": "caption",
            "content_blocks": [{"type": "text", "text": "from blocks"}],
            "mime_data": [{"mime_type": "image/png", "mime_bytes": "AAAA"}],
        }
        blocks = ContentUtils.blocks_from_chat_message(chat_message)
        assert blocks == [{"type": "text", "text": "from blocks"}]

    def test_blocks_from_chat_message_maps_mime_data(self):
        """
        The simple-client mime_data shape maps to text + data blocks, with
        the data-block type chosen from the MIME prefix.
        """
        chat_message = {
            "type": "HUMAN",
            "text": "Describe this image.",
            "mime_data": [
                {"mime_type": "image/png", "mime_bytes": "aW1n"},
                {"mime_type": "audio/wav", "mime_bytes": "YXVk"},
                {"mime_type": "application/pdf", "mime_bytes": "cGRm"},
                {"mime_type": "text/plain", "mime_bytes": "dHh0"},
            ],
        }
        blocks = ContentUtils.blocks_from_chat_message(chat_message)
        assert blocks[0] == {"type": "text", "text": "Describe this image."}
        assert blocks[1] == {"type": "image", "base64": "aW1n", "mime_type": "image/png"}
        assert blocks[2] == {"type": "audio", "base64": "YXVk", "mime_type": "audio/wav"}
        assert blocks[3] == {"type": "file", "base64": "cGRm", "mime_type": "application/pdf"}
        assert blocks[4] == {"type": "text-plain", "mime_type": "text/plain", "base64": "dHh0"}

    def test_flatten_matches_langchain_text_for_non_string_text_values(self):
        """
        A text block whose "text" value is not a string contributes nothing -
        exactly like langchain's own BaseMessage.text (never the literal
        "None").
        """
        content = [{"type": "text", "text": None}, {"type": "text", "text": 5}]
        message = AIMessage(content=content)
        assert ContentUtils.flatten_to_text(message) == ""
        assert ContentUtils.flatten_to_text(message) == str(message.text)
        assert ContentUtils.is_empty_content(message)

    def test_normalize_content_collapses_list_of_str(self):
        """
        List-of-strings content has no block structure to preserve - it
        collapses to the concatenated text, not a multi-text-block list.
        """
        assert ContentUtils.normalize_content(ContentFixtures.list_of_str()) == "part one, part two"

    def test_normalize_message_is_idempotent(self):
        """
        Applying normalize_message twice yields the same content and metadata
        as applying it once (the v1 stamp prevents re-translation).
        """
        once = ContentUtils.normalize_message(ContentFixtures.anthropic_thinking_first())
        twice = ContentUtils.normalize_message(once)
        assert twice.content == once.content
        assert twice.response_metadata == once.response_metadata

    def test_utils_handle_message_chunks(self):
        """
        Chunk messages neither crash the projections nor leak
        tool_call_chunk blocks into the standardized view.
        """
        chunk = AIMessageChunk(content=[
            {"type": "text", "text": "partial", "index": 0},
            {"type": "tool_call_chunk", "name": "f", "args": '{"x"', "id": "c1", "index": 1},
        ])
        assert ContentUtils.flatten_to_text(chunk) == "partial"
        assert [block["type"] for block in ContentUtils.standard_blocks(chunk)] == ["text"]

    def test_is_trivial_ignores_provider_id_keys(self):
        """
        Locked policy: bookkeeping keys (id/index) do not make a text block
        non-trivial - such messages are plain strings on today's wire, and
        the collapse deliberately drops those keys.
        """
        assert ContentUtils.is_trivial([{"type": "text", "text": "hi", "id": "msg_1", "index": 0}])

    def test_history_safe_text_references_data_blocks(self):
        """
        The assistant-history projection keeps text and replaces data blocks
        with a short reference - an image-only tool result must not become
        empty history.
        """
        assert ContentUtils.history_safe_text(ContentFixtures.mcp_tool_content()) == \
            "Here is the chart.[image attachment: image/png]"
        image_only = [{"type": "image", "base64": "AAAA", "mime_type": "image/png"}]
        assert ContentUtils.history_safe_text(image_only) == "[image attachment: image/png]"
        # Plain strings and text-plain inline text pass through.
        assert ContentUtils.history_safe_text("plain") == "plain"
        assert ContentUtils.history_safe_text(
            [{"type": "text-plain", "mime_type": "text/plain", "text": "inline doc"}]) == "inline doc"

    def test_blocks_from_chat_message_text_only_and_malformed(self):
        """
        Text-only messages yield None (callers keep today's path), and
        malformed mime_data yields None (callers fall back to text).
        """
        assert ContentUtils.blocks_from_chat_message(None) is None
        assert ContentUtils.blocks_from_chat_message({"type": "HUMAN", "text": "hi"}) is None
        assert ContentUtils.blocks_from_chat_message(
            {"type": "HUMAN", "text": "hi", "mime_data": []}) is None
        # Raw bytes / missing fields are malformed: base64 strings only.
        assert ContentUtils.blocks_from_chat_message(
            {"type": "HUMAN", "mime_data": [{"mime_type": "image/png", "mime_bytes": b"raw"}]}) is None
        assert ContentUtils.blocks_from_chat_message(
            {"type": "HUMAN", "mime_data": [{"mime_type": "image/png"}]}) is None
        assert ContentUtils.blocks_from_chat_message(
            {"type": "HUMAN", "mime_data": [{"mime_bytes": "AAAA"}]}) is None

    def test_blocks_from_chat_message_malformed_content_blocks_fails_safe(self):
        """
        A present-but-invalid content_blocks value yields None - it must NOT
        fall through to the mime_data mapping (fail safe to text-only).
        """
        chat_message = {
            "type": "HUMAN",
            "text": "caption",
            "content_blocks": [{"type": "bogus-type", "x": 1}],
            "mime_data": [{"mime_type": "image/png", "mime_bytes": "AAAA"}],
        }
        assert ContentUtils.blocks_from_chat_message(chat_message) is None
