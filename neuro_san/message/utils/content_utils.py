
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

import base64
import math

from langchain_core.messages.base import BaseMessage

from neuro_san.message.content_blocks.content_blocks_format import ContentBlocksFormat
from neuro_san.message.content_blocks.content_blocks_format_registry import ContentBlocksFormatRegistry
from neuro_san.message.utils.decode_utils import DecodeUtils


class ContentUtils:
    """
    The single policy for flattening, inspecting and reducing langchain
    message content that can be either a plain string or a list of content
    blocks (see
    https://docs.langchain.com/oss/python/langchain/messages#message-content).

    Every place in the codebase that needs to reduce message content to text,
    or to a block list in the message's format, must go through this class
    so that the projections cannot diverge.

    A message's content is handled by the format whose mark it carries, or
    by the default format of ContentBlocksFormatRegistry when it carries
    none, as content fresh from a provider does. Blocks the server builds
    itself (tool results, mime_data mapping) are in the default format.
    Inbound wire content uses the format its content_blocks wrapper names.
    The rules of each format live in its ContentBlocksFormat class, not here.

    This is framework plumbing, NOT a client-facing API (much like
    SlyDataRedactor in this same package). Clients should keep consuming
    ChatMessage dictionaries via the message processors. It lives in
    neuro_san.message rather than neuro_san.internals because its first
    consumers are in this package, and neuro_san.message deliberately never
    imports from neuro_san.internals.
    """

    @staticmethod
    def flatten_to_text(source: Union[BaseMessage, str, List[Any], None]) -> str:
        """
        Project message content down to its visible text.

        Follows langchain's BaseMessage.text semantics: concatenate top-level
        strings and the "text" field of {"type": "text"} blocks, in order.
        Other block types (reasoning, image, etc.) contribute nothing.
        Unlike some call sites, this method never strips whitespace -
        callers that strip today must keep stripping themselves.

        :param source: A BaseMessage, or raw message content
                (a string, or a list of strings and/or block dictionaries)
        :return: The concatenated text. Never None; empty content yields "".
        """
        content: Any = source
        if isinstance(source, BaseMessage):
            source_message: BaseMessage = source
            content = source_message.content
        if content is None:
            return ""
        if isinstance(content, str):
            content_string: str = content
            return content_string
        if not isinstance(content, list):
            # Not a legal langchain content shape, but do not crash over it.
            return str(content)

        content_list: List[Any] = content
        parts: List[str] = []
        # Collect the text of each item, in order.
        item: Any = None
        for item in content_list:
            if isinstance(item, str):
                item_string: str = item
                parts.append(item_string)
            elif isinstance(item, dict):
                item_dict: Dict[str, Any] = item
                if item_dict.get("type") == "text":
                    text_value: Any = item_dict.get("text")
                    # Like BaseMessage.text, a non-string text value contributes
                    # nothing (never the literal "None").
                    if isinstance(text_value, str):
                        text_value_string: str = text_value
                        parts.append(text_value_string)
        return "".join(parts)

    @staticmethod
    def is_empty_content(source: Union[BaseMessage, str, List[Any], None]) -> bool:
        """
        Determine whether message content carries no actionable payload.

        A whitespace-only string, an empty list, or a list whose every element
        is a blank string or a blank text block all count as empty.
        Any non-text block (reasoning, image, ...) counts as content.

        NOTE for wire-conversion use: today's ChatMessage wire format emits
        text="" for empty *string* content and omits the text key only for
        empty *list* content, so a text-omission gate built on this method
        must apply it to list-form content only (golden parity).

        :param source: A BaseMessage, or raw message content
        :return: True if the content is empty in the sense above
        """
        content: Any = source
        if isinstance(source, BaseMessage):
            source_message: BaseMessage = source
            content = source_message.content

        if content is None:
            return True

        if isinstance(content, str):
            string_content: str = content
            return string_content.strip() == ""

        if isinstance(content, list):
            list_content: List[Any] = content
            for item in list_content:
                if not ContentUtils._is_blank_block(item):
                    return False
            return True

        return not bool(content)

    @staticmethod
    def _is_blank_block(item: Any) -> bool:
        """
        Determine whether a single list-content item carries no visible text.

        :param item: One element of a message's list content
        :return: True for a whitespace-only string or an empty/whitespace text
                 block ({"type": "text"}); any other block type counts as content
        """
        if isinstance(item, str):
            return item.strip() == ""
        if isinstance(item, dict) and item.get("type") == "text":
            text_value: Any = item.get("text")
            if not isinstance(text_value, str):
                # Like BaseMessage.text, a non-string text value is no text.
                return True
            return text_value.strip() == ""
        return False

    @staticmethod
    def standard_blocks(message: BaseMessage) -> List[Dict[str, Any]]:
        """
        Get the standardized content-block view of a message: the block view
        of the format the message is in (see
        ContentBlocksFormatRegistry.format_for_message), sanitized to be
        JSON-safe (bytes become base64 strings).

        Call this while the message's response_metadata is still intact: the
        format reads it to decide how to translate provider-native content.
        Which blocks each provider shape becomes is the format's business.

        :param message: The BaseMessage whose content to standardize
        :return: A JSON-safe list of content-block dictionaries in the message's format
        """
        blocks_format: ContentBlocksFormat = ContentBlocksFormatRegistry.format_for_message(message)
        blocks: List[Dict[str, Any]] = blocks_format.blocks_of(message)
        json_safe_blocks: List[Dict[str, Any]] = ContentUtils.to_json_safe(blocks)
        return json_safe_blocks

    @staticmethod
    def wrap_content_blocks(blocks: List[Dict[str, Any]],
                            blocks_format: Optional[ContentBlocksFormat] = None) -> Dict[str, Any]:
        """
        Build the ChatMessage.content_blocks wrapper (see ContentBlocks in
        chat.proto) around a list of blocks.

        This and unwrap_content_blocks are the only two places that know the
        wrapper's layout; the format names live in the registry.

        :param blocks: A JSON-safe list of content-block dictionaries
        :param blocks_format: The format the blocks are in. None means the
                server's default format (see ContentBlocksFormatRegistry).
        :return: The wrapper dictionary: {"format": <the format's name>, "blocks": blocks}
        """
        use_format: Optional[ContentBlocksFormat] = blocks_format
        if use_format is None:
            use_format = ContentBlocksFormatRegistry.get_default()
        wrapper: Dict[str, Any] = {
            "format": use_format.get_name(),
            "blocks": blocks,
        }
        return wrapper

    @staticmethod
    def unwrap_content_blocks(wrapper: Any) -> Optional[List[Dict[str, Any]]]:
        """
        Take the blocks back out of a ChatMessage.content_blocks wrapper.

        The blocks themselves are returned as-is, not validated (see
        looks_like_blocks for that). An empty wrapper is one whose "blocks"
        member is absent, None or an empty list: proto3 JSON omits an empty
        repeated field, so these are one and the same on the wire, and such a
        wrapper carries nothing whatever its format says.

        :param wrapper: The value of a "content_blocks" key
        :return: The blocks list; an empty list for an empty wrapper; None when
                 the value is not a wrapper (a bare list, the shape from before
                 the format tag), its blocks are not a list, or its format is
                 one this code does not know - callers fall back to text
        """
        if not isinstance(wrapper, dict):
            return None
        wrapper_dict: Dict[str, Any] = wrapper

        blocks: Any = wrapper_dict.get("blocks")
        if blocks is None:
            return []
        if not isinstance(blocks, list):
            return None
        blocks_list: List[Dict[str, Any]] = blocks
        if len(blocks_list) == 0:
            return []

        if ContentUtils.content_blocks_format(wrapper_dict) is None:
            return None
        return blocks_list

    @staticmethod
    def content_blocks_format(wrapper: Any) -> Optional[ContentBlocksFormat]:
        """
        Find the format a ChatMessage.content_blocks wrapper says its
        blocks are in.

        :param wrapper: The value of a "content_blocks" key
        :return: The ContentBlocksFormat named by the wrapper's "format",
                 or None when the value is not a wrapper or names a format
                 this server does not know
        """
        if not isinstance(wrapper, dict):
            return None
        wrapper_dict: Dict[str, Any] = wrapper
        return ContentBlocksFormatRegistry.get_format(wrapper_dict.get("format"))

    @staticmethod
    def normalize_content(message: BaseMessage) -> Union[str, List[Dict[str, Any]]]:
        """
        Reduce a message's content to its canonical in-server form:
        plain-string content stays a plain string; block-form content becomes
        the block list of the message's format, unless it is empty or the
        format calls it trivial, in which case it collapses to its flattened
        text so that text-only traffic keeps its exact current shape.

        :param message: The BaseMessage whose content to normalize
        :return: A string, or a JSON-safe list of standard block dictionaries
        """
        content: Any = message.content
        if isinstance(content, str):
            content_string: str = content
            return content_string

        if isinstance(content, list):
            content_list: List[Any] = content
            all_strings: bool = True
            item: Any = None
            for item in content_list:
                if not isinstance(item, str):
                    all_strings = False
                    break
            if all_strings:
                # A list of plain strings carries no block structure at all -
                # collapse to text rather than promoting it to a block list.
                return ContentUtils.flatten_to_text(message)

        blocks_format: ContentBlocksFormat = ContentBlocksFormatRegistry.format_for_message(message)
        blocks: List[Dict[str, Any]] = ContentUtils.standard_blocks(message)
        if not blocks or blocks_format.is_trivial(blocks):
            return ContentUtils.flatten_to_text(message)

        return blocks

    @staticmethod
    def normalize_message(message: BaseMessage) -> BaseMessage:
        """
        Return a copy of the message whose content is normalize_content()'s
        canonical form. When that form is a block list, the copy's
        response_metadata is marked by the format so that a later block view
        of the copy returns these blocks as they are.

        Intended for COMPLETE messages. Do not use on AIMessageChunks:
        chunk-only shapes (e.g. a tool_call_chunk block living solely in
        chunk content) are not content and would be collapsed away.

        :param message: The BaseMessage to normalize
        :return: The same message instance if nothing changed,
                 otherwise a model_copy with normalized content
        """
        update_dict: Dict[str, Any] = {}
        normalized: Union[str, List[Dict[str, Any]]] = ContentUtils.normalize_content(message)
        if isinstance(normalized, str):
            if normalized == message.content:
                return message
            update_dict["content"] = normalized
            return ContentUtils.message_model_copy(message, update_dict)

        blocks_format: ContentBlocksFormat = ContentBlocksFormatRegistry.format_for_message(message)
        update_dict = {
            "content": normalized,
            "response_metadata": blocks_format.response_metadata_for(message),
        }
        return ContentUtils.message_model_copy(message, update_dict)

    @staticmethod
    def message_model_copy(message: BaseMessage, update_dict: Dict[str, Any]) -> BaseMessage:
        """
        Funnel method to return a model_copy() of the message with the given update_dict applied.

        :param message: The BaseMessage to copy
        :param update_dict: The dictionary to update the message with
        :return: A model_copy() of the message with the update_dict applied
        """
        return message.model_copy(update=update_dict)

    @staticmethod
    def looks_like_blocks(value: Any) -> bool:
        """
        Determine whether a value is a non-empty list of block dictionaries
        in the server's default format that can be used as message content.
        What qualifies is the format's decision (see its is_block_list).

        :param value: Any value to inspect
        :return: True if the value can be used as block content
        """
        default_format: ContentBlocksFormat = ContentBlocksFormatRegistry.get_default()
        return default_format.is_block_list(value)

    # pylint: disable=too-many-return-statements
    @staticmethod
    def blocks_from_chat_message(chat_message: Optional[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """
        Extract content blocks from a neuro-san ChatMessage dictionary, if
        it carries any block-form content.

        Precedence:
        1. A "content_blocks" wrapper ({"format": <a format this server
           knows>, "blocks": [...]} per chat.proto) supplies its blocks list
           as-is.
           A wrapper with a format this code does not know, a bare list, or
           blocks that are NOT valid standard blocks yields None (fail safe)
           - it does not fall through to mime_data. A wrapper with no blocks
           (member absent, null or an empty list - proto3 JSON omits an empty
           repeated field, so these are one and the same on the wire) carries
           nothing and does fall through, whatever its format says: a format
           can only be judged against blocks. Note the returned list aliases
           the caller's list; callers must not mutate the result.
        2. Otherwise a non-empty "mime_data" list ({"mime_type": ...,
           "mime_bytes": <base64 string>} entries per chat.proto) is mapped to
           data blocks of the default format, preceded by a text block for
           any "text" field.
        3. Otherwise there is no block content.

        :param chat_message: A ChatMessage dictionary
        :return: A list of block dictionaries, or None if the
                 message carries no usable block-form content (including
                 when content_blocks or mime_data entries are malformed -
                 callers should fall back to their existing text-only
                 handling)
        """
        if chat_message is None:
            return None

        content_blocks: Any = chat_message.get("content_blocks")
        if content_blocks is not None:
            unwrapped: Optional[List[Dict[str, Any]]] = ContentUtils.unwrap_content_blocks(content_blocks)
            if unwrapped is None:
                # Not a wrapper this code knows: fail safe to text.
                return None
            if len(unwrapped) > 0:
                blocks_format: ContentBlocksFormat = ContentUtils.content_blocks_format(content_blocks)
                if blocks_format.is_block_list(unwrapped):
                    return unwrapped
                return None
            # An empty wrapper carries nothing; fall through to mime_data.

        mime_data: Any = chat_message.get("mime_data")
        if not isinstance(mime_data, list):
            return None

        mime_data_list: List[Any] = mime_data
        if len(mime_data_list) == 0:
            return None

        default_format: ContentBlocksFormat = ContentBlocksFormatRegistry.get_default()
        blocks: List[Dict[str, Any]] = []
        text: Any = chat_message.get("text")
        if isinstance(text, str) and text:
            blocks.append(default_format.text_block(text))

        # Map each MimeData entry to a data block, in order.
        entry: Any = None
        for entry in mime_data_list:

            if not isinstance(entry, dict):
                return None
            entry_dict: Dict[str, Any] = entry

            mime_type: str = str(entry_dict.get("mime_type") or "")
            mime_bytes: Any = entry_dict.get("mime_bytes")
            if not isinstance(mime_bytes, str) or not mime_bytes or not mime_type:
                return None
            mime_bytes_str: str = mime_bytes
            blocks.append(default_format.data_block(mime_type, mime_bytes_str))

        return blocks

    @staticmethod
    def history_safe_text(source: Union[BaseMessage, str, List[Any], None]) -> str:
        """
        Project content to text that is safe to replay as assistant-role
        conversation history. Text contributes as in flatten_to_text, but
        the format the content is in replaces its data blocks with a short
        text reference instead of letting them vanish, so an image-only tool
        result does not become empty history. Providers reject raw data
        blocks in assistant-role messages, which is why history copies must
        go through this projection.

        :param source: A BaseMessage, or raw message content
        :return: The history-safe text. Never None.
        """
        content: Any = source
        # Raw content carries no mark, so it is in the server's default format.
        blocks_format: ContentBlocksFormat = ContentBlocksFormatRegistry.get_default()
        if isinstance(source, BaseMessage):
            source_message: BaseMessage = source
            content = source_message.content
            blocks_format = ContentBlocksFormatRegistry.format_for_message(source_message)

        if content is None or isinstance(content, str):
            content_string: str = content
            return content_string or ""

        if not isinstance(content, list):
            return str(content)

        content_list: List[Any] = content
        return blocks_format.history_safe_text(content_list)

    @staticmethod
    def restorable_blocks(chat_message: Optional[Dict[str, Any]],
                          for_chat_history: bool = False) -> Optional[List[Dict[str, Any]]]:
        """
        Decide what block content, if any, a message rebuilt from a ChatMessage
        dictionary should carry. This is the inbound counterpart of the
        content_blocks wrapper that to_dict emits.

        The wrapper's format (see content_blocks_format) keeps the blocks a
        model can be given again and drops the rest.
        A message bound for a model's chat history also loses what the
        format says such history cannot take yet. What remains is used only
        if its text is the message's text, when the message has one, and it
        says something beyond that text: a lone text block that only repeats
        the text adds nothing (see the format's is_trivial).

        :param chat_message: A ChatMessage dictionary
        :param for_chat_history: True when the message will be replayed to a
                model as chat history, which holds some blocks back
        :return: The blocks to use as the message content, or None when the
                 message should keep its text as content: no wrapper, a format
                 this server does not know, nothing left after the format's
                 restore, blocks equivalent to the text, or blocks whose text
                 is not the message's text.
                 The returned blocks are the caller's own dictionaries.
        """
        wrapper: Any = None
        if chat_message is not None:
            wrapper = chat_message.get("content_blocks")
        blocks_format: Optional[ContentBlocksFormat] = ContentUtils.content_blocks_format(wrapper)
        if blocks_format is None:
            # No message, no wrapper, or a format this server does not know.
            return None

        unwrapped: Optional[List[Dict[str, Any]]] = ContentUtils.unwrap_content_blocks(wrapper)
        if unwrapped is None or len(unwrapped) == 0:
            return None

        kept: List[Dict[str, Any]] = blocks_format.restore_blocks(unwrapped, for_chat_history=for_chat_history)
        if len(kept) == 0:
            return None

        text: Any = chat_message.get("text")
        message_text: str = ""
        if isinstance(text, str):
            message_text = text
        blocks_text: str = ContentUtils.flatten_to_text(kept)
        if len(message_text) > 0 and blocks_text != message_text:
            # The blocks do not add up to the text the message has, so using
            # them would change or lose it. Fail safe to the text.
            return None
        if blocks_format.is_trivial(kept) and blocks_text == message_text:
            return None
        return kept

    @staticmethod
    def to_json_safe(value: Any) -> Any:
        """
        Recursively make a value JSON-serializable without dropping data:
        bytes become base64 strings, non-finite floats and unknown objects
        become their string form, tuples and sets become lists, and
        dictionary keys become strings. Use it for message content and
        content-block payloads (tool outputs, images, files) that must
        survive intact into the journal.

        Not to be confused with ChatMessageConverter.to_json_safe, the lossy
        variant for outbound ChatMessage response dictionaries: there
        anything non-serializable, bytes included, becomes None and
        non-string keys are dropped. Use that one for response
        dictionaries, this one for content.

        :param value: Any value to sanitize
        :return: A JSON-serializable equivalent of the value
        """
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)
        if isinstance(value, (bytes, bytearray)):
            # Convert bytes to base64
            bytes_value: bytes = bytes(value)
            encoded: bytes = base64.b64encode(bytes_value)
            return DecodeUtils.decode(encoded, "ascii")
        if isinstance(value, dict):
            safe_dict: Dict[str, Any] = {}
            for key, item in value.items():
                safe_dict[str(key)] = ContentUtils.to_json_safe(item)
            return safe_dict
        if isinstance(value, (list, tuple, set)):
            safe_list: List[Any] = []
            for item in value:
                safe_list.append(ContentUtils.to_json_safe(item))
            return safe_list
        return str(value)
