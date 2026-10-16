
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
from typing import Union

from copy import copy

from langchain_core.messages.base import BaseMessage
from langchain_core.messages.content import KNOWN_BLOCK_TYPES
from typing_extensions import override

from neuro_san.message.content_blocks.content_blocks_format import ContentBlocksFormat


class LangchainV1ContentBlocksFormat(ContentBlocksFormat):
    """
    The "langchain_v1" content_blocks format: LangChain's standard content
    blocks (see https://docs.langchain.com/oss/python/langchain/messages#message-content).

    Each block is a dictionary whose "type" names its shape: "text",
    "reasoning", a data type ("image", "audio", "video", "file",
    "text-plain"), "non_standard" for a provider's own shape, or one of
    the tool-call bookkeeping types this format never treats as content.
    """

    NAME: str = "langchain_v1"

    # The response_metadata value that tells LangChain the message content
    # already holds standard blocks, so .content_blocks must pass it
    # through instead of re-running a provider translator over it
    # (which would wrap already-standard blocks as "non_standard").
    OUTPUT_VERSION: str = "v1"

    # Block types that AIMessage.content_blocks merges in from the message's
    # .tool_calls field (or their chunk/invalid variants). A tool call is not
    # message content: outbound these are left out of the standardized view,
    # and inbound they are dropped.
    TOOL_CALL_BLOCK_TYPES: List[str] = ["tool_call", "tool_call_chunk", "invalid_tool_call"]

    # Blocks no provider accepts as input again: records of a provider's own
    # server-side tool use, which pair with state a replay cannot reproduce,
    # and non_standard blocks, which carry one provider's native shape.
    NOT_INPUT_BLOCK_TYPES: List[str] = ["server_tool_call", "server_tool_call_chunk", "server_tool_result",
                                        "non_standard"]

    # Block types whose payload is data, not conversation text.
    # Providers reject these in assistant-role history, so history
    # projections replace them with a short text reference instead.
    DATA_BLOCK_TYPES: List[str] = ["image", "audio", "video", "file", "text-plain"]

    # Keys of a text block that carry no information beyond its text:
    # its type, the text itself, and provider bookkeeping (id, index).
    TRIVIAL_TEXT_BLOCK_KEYS: List[str] = ["type", "text", "id", "index"]

    @override
    def get_name(self) -> str:
        """
        Give the name this format has on the wire.

        :return: The "format" value that names this format on the wire
        """
        return LangchainV1ContentBlocksFormat.NAME

    @override
    def is_block_list(self, value: Any) -> bool:
        """
        Determine whether a value is a non-empty list of standard content
        blocks (see is_content_block for what qualifies).

        :param value: Any value to inspect
        :return: True if the value can be used as standard block content
        """
        if not isinstance(value, list):
            return False
        list_value: List[Any] = value
        if len(list_value) == 0:
            return False

        # Every element must be a standard content block.
        item: Any = None
        for item in list_value:
            if not self.is_content_block(item):
                return False
        return True

    def is_content_block(self, item: Any) -> bool:
        """
        Determine whether one list element is a standard block that counts
        as message content. Does not qualify:
        - a block whose "type" is not a string,
        - a provider-native shape (e.g. Anthropic {"type": "thinking"}),
        - a v0-era block (marked by a "source_type" key),
        - a tool-call block (see TOOL_CALL_BLOCK_TYPES).

        :param item: One element of a block list
        :return: True if the element is a standard content block
        """
        if not isinstance(item, dict):
            return False
        item_dict: Dict[str, Any] = item

        item_type: Any = item_dict.get("type")
        # Only a string can be looked up in the set of known types.
        if not isinstance(item_type, str):
            return False
        if item_type not in KNOWN_BLOCK_TYPES:
            return False
        if item_type in LangchainV1ContentBlocksFormat.TOOL_CALL_BLOCK_TYPES:
            return False
        if "source_type" in item_dict:
            return False
        return True

    @override
    def blocks_of(self, message: BaseMessage) -> List[Dict[str, Any]]:
        """
        Give the standard content-block view of a message, for the outbound
        wire.

        Reads the message's .content_blocks property, which translates
        provider-native content (Anthropic "thinking" dicts, OpenAI Responses
        reasoning items, additional_kwargs reasoning) into standard blocks,
        and leaves out the tool-call blocks that property merges in from
        .tool_calls (see TOOL_CALL_BLOCK_TYPES). The blocks are not made
        JSON-safe here.

        Call this while the message's response_metadata (model_provider /
        output_version) is still intact: translator selection depends on it.
        Messages lacking model_provider metadata (and Anthropic
        redacted_thinking blocks even with it) standardize provider-native
        shapes as {"type": "non_standard", "value": ...} wrappers: data-
        preserving, but downstream renderers must expect them.

        :param message: The BaseMessage whose content to view as blocks
        :return: The standard content blocks of the message, in order
        """
        blocks: List[Dict[str, Any]] = []

        content_blocks: List[Dict[str, Any]] = message.content_blocks
        # Keep every block that is message content, in order.
        block: Dict[str, Any] = None
        for block in content_blocks:
            use_block: Dict[str, Any] = block
            block_type: str = use_block.get("type")
            if block_type in LangchainV1ContentBlocksFormat.TOOL_CALL_BLOCK_TYPES:
                continue
            blocks.append(use_block)
        return blocks

    @override
    def is_trivial(self, blocks: List[Dict[str, Any]]) -> bool:
        """
        Determine whether a standardized block list carries no more information
        than its flattened text: a single text block whose only keys are those
        in TRIVIAL_TEXT_BLOCK_KEYS, or whose other keys are empty. Trivial block
        lists collapse back to plain-string content so that existing text-only
        traffic keeps its exact current shape.

        Policy: provider bookkeeping keys ("id", "index") do NOT make a text
        block non-trivial - such messages are plain strings on today's wire,
        and the collapse deliberately drops those keys to keep that shape. Any
        other key with a value (annotations, extras, an OpenAI Responses
        "phase", ...) does, so the collapse never drops information a client
        could use.

        :param blocks: A list of standard content-block dictionaries
        :return: True if the list is equivalent to a plain string
        """
        if len(blocks) != 1:
            return False
        block: Dict[str, Any] = blocks[0]
        if block.get("type") != "text":
            return False
        # Any key beyond the trivial ones that holds a value makes the block say more than its text.
        key: str = None
        value: Any = None
        for key, value in block.items():
            if key in LangchainV1ContentBlocksFormat.TRIVIAL_TEXT_BLOCK_KEYS:
                continue
            if LangchainV1ContentBlocksFormat.is_empty_value(value):
                continue
            return False
        return True

    @staticmethod
    def is_empty_value(value: Any) -> bool:
        """
        Determine whether a block field value carries nothing: None, an empty
        string, an empty list or an empty dictionary.

        :param value: The value of one key of a content block
        :return: True if the value is empty in that sense
        """
        if value is None:
            return True
        if isinstance(value, str):
            return len(value) == 0
        if isinstance(value, list):
            return len(value) == 0
        if isinstance(value, dict):
            return len(value) == 0
        return False

    @override
    def restore_blocks(self, blocks: List[Any], for_chat_history: bool = False) -> List[Dict[str, Any]]:
        """
        Keep the blocks a model can be given again: text blocks with a text
        string (every other key, such as an OpenAI "phase", stays with them)
        and reasoning blocks that carry something. Data blocks are dropped
        because attachments are not sent to a model yet. Tool-call blocks,
        blocks no provider takes as input (see NOT_INPUT_BLOCK_TYPES) and
        anything malformed are dropped too. Whether a kept reasoning block
        still pairs with its provider state is for the provider to judge.

        Blocks bound for a model's chat history also lose their reasoning
        blocks (see without_reasoning).

        :param blocks: The "blocks" list of an inbound content_blocks wrapper
        :param for_chat_history: True when the blocks will be replayed to a
                model as chat history, which holds reasoning blocks back
        :return: The surviving blocks, the same dictionaries, in order
        """
        kept: List[Dict[str, Any]] = []
        # Keep each block a model can be given again, in order.
        item: Any = None
        for item in blocks:
            block: Optional[Dict[str, Any]] = self.restore_block(item)
            if block is not None:
                kept.append(block)
        if for_chat_history:
            kept = self.without_reasoning(kept)
        return kept

    def restore_block(self, item: Any) -> Optional[Dict[str, Any]]:
        """
        Decide whether one inbound block is kept.

        :param item: One element of the inbound "blocks" list
        :return: The block itself, or None to drop it
        """
        if not self.is_content_block(item):
            return None
        block: Dict[str, Any] = item

        block_type: str = block.get("type")
        if block_type in LangchainV1ContentBlocksFormat.NOT_INPUT_BLOCK_TYPES:
            return None
        if block_type == "text":
            return self.restore_text_block(block)
        if block_type == "reasoning":
            return self.restore_reasoning_block(block)
        # Data blocks, and any block type this method does not know how to
        # replay, are dropped. Attachments are not sent to a model yet.
        return None

    def restore_text_block(self, block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        A text block needs a text string. Every other key stays with it.

        :param block: A block whose type is "text"
        :return: The block, or None when it has no text string
        """
        text: Any = block.get("text")
        # An empty string is still text; only a missing or non-string one fails.
        if not isinstance(text, str):
            return None
        return block

    def restore_reasoning_block(self, block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        A reasoning block must carry something: reasoning text, an id, or
        provider extras such as a signature or an encrypted copy.

        :param block: A block whose type is "reasoning"
        :return: The block, or None when it carries nothing
        """
        if self.has_string_value(block, "reasoning"):
            return block
        if self.has_string_value(block, "id"):
            return block
        extras: Any = block.get("extras")
        if not isinstance(extras, dict):
            return None
        extras_dict: Dict[str, Any] = extras
        if len(extras_dict) > 0:
            return block
        return None

    def without_reasoning(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Leave reasoning blocks out of a block list.

        A provider replays only the reasoning it produced itself, and the
        wire does not yet say which provider produced a block, so reasoning
        cannot be replayed safely yet.

        :param blocks: A list of standard content-block dictionaries
        :return: A new list with the same blocks minus the reasoning ones
        """
        remaining: List[Dict[str, Any]] = []
        # Copy every block except the reasoning ones.
        block: Dict[str, Any] = None
        for block in blocks:
            if block.get("type") != "reasoning":
                remaining.append(block)
        return remaining

    @staticmethod
    def has_string_value(block: Dict[str, Any], key: str) -> bool:
        """
        Check whether a block holds a non-empty string under a key.

        :param block: A content block
        :param key: The key to look at
        :return: True if the key holds a non-empty string
        """
        value: Any = block.get(key)
        if not isinstance(value, str):
            return False
        return len(value) > 0

    @override
    def history_safe_text(self, content: List[Any]) -> str:
        """
        Project list content to text that is safe to replay as assistant-role
        conversation history. Strings and the text of text blocks contribute
        as they are. A data block (see DATA_BLOCK_TYPES) contributes its
        inline text when it has one, and otherwise a short
        "[<type> attachment: <mime_type>]" reference, so that an image-only
        tool result does not become empty history.

        :param content: A message's list content: strings and/or blocks
        :return: The history-safe text. Never None.
        """
        parts: List[str] = []
        # Project each item to its history-safe text, in order.
        item: Union[Dict[str, Any], str] = None
        for item in content:

            if isinstance(item, str):
                string_item: str = item
                parts.append(string_item)
                continue

            if not isinstance(item, dict):
                continue

            dict_item: Dict[str, Any] = item

            block_type: Any = dict_item.get("type")
            if block_type == "text":
                text_value: Any = dict_item.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
            elif block_type in LangchainV1ContentBlocksFormat.DATA_BLOCK_TYPES:
                inline_text: Any = dict_item.get("text")
                if isinstance(inline_text, str) and inline_text:
                    # A text-plain block can carry its text inline.
                    parts.append(inline_text)
                else:
                    mime_type: str = str(dict_item.get("mime_type") or "unknown")
                    parts.append(f"[{block_type} attachment: {mime_type}]")
        return "".join(parts)

    @override
    def text_block(self, text: str) -> Dict[str, Any]:
        """
        Build a standard text block.

        :param text: The text the block carries
        :return: A text block dictionary
        """
        block: Dict[str, Any] = {
            "type": "text",
            "text": text,
        }
        return block

    @override
    def data_block(self, mime_type: str, base64_str: str) -> Dict[str, Any]:
        """
        Build the standard data block for one MimeData entry (see chat.proto).
        The block type follows the MIME type's prefix; anything that is not
        an image, audio or video is a file.

        :param mime_type: The MIME type of the data
        :param base64_str: The data as a base64 string (never raw bytes)
        :return: A standard data-block dictionary
        """
        if mime_type == "text/plain":
            # PlainTextContentBlock requires its mime_type literal.
            plain_text_block: Dict[str, Any] = {
                "type": "text-plain",
                "mime_type": "text/plain",
                "base64": base64_str,
            }
            return plain_text_block

        kind: str = "file"
        # The first media prefix that matches names the block type.
        prefix: str = None
        for prefix in ("image", "audio", "video"):
            if mime_type.startswith(f"{prefix}/"):
                kind = prefix
                break
        block: Dict[str, Any] = {
            "type": kind,
            "base64": base64_str,
            "mime_type": mime_type,
        }
        return block

    @override
    def is_format_of(self, message: BaseMessage) -> bool:
        """
        Determine whether a message is marked as carrying standard v1 blocks:
        its response_metadata says output_version OUTPUT_VERSION.

        :param message: The BaseMessage to inspect
        :return: True if the message carries the v1 mark
        """
        response_metadata: Optional[Dict[str, Any]] = message.response_metadata
        if response_metadata is None:
            return False
        return response_metadata.get("output_version") == LangchainV1ContentBlocksFormat.OUTPUT_VERSION

    @override
    def response_metadata_for(self, message: BaseMessage) -> Dict[str, Any]:
        """
        Build the response_metadata of a message whose content is standard
        blocks: a copy of the message's own with output_version set to
        OUTPUT_VERSION, so that a later .content_blocks access passes the
        blocks through instead of re-translating them.

        :param message: The BaseMessage whose response_metadata to start from
        :return: A new response_metadata dictionary
        """
        response_metadata: Dict[str, Any] = None
        if message.response_metadata is None:
            response_metadata = {}
        else:
            response_metadata = copy(message.response_metadata)
        response_metadata["output_version"] = LangchainV1ContentBlocksFormat.OUTPUT_VERSION
        return response_metadata
