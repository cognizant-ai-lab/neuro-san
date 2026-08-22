
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
from langchain_core.messages.content import KNOWN_BLOCK_TYPES


class ContentUtils:
    """
    The single policy for flattening, standardizing and inspecting
    langchain message content that can be either a plain string or a list
    of content blocks (see
    https://docs.langchain.com/oss/python/langchain/messages#message-content).

    Every place in the codebase that needs to reduce message content to text,
    or to a standardized block list, must go through this class so that the
    projections cannot diverge.

    This is framework plumbing, NOT a client-facing API (much like
    SlyDataRedactor in this same package). Clients should keep consuming
    ChatMessage dictionaries via the message processors. The planned
    consumers (see issue #1222 for the full map) are the wire converter in
    neuro_san.message.types, the reasoning-surfacing message processors and
    filters in neuro_san.message, and the capture/journaling/session code in
    neuro_san.internals. It lives in neuro_san.message rather than
    neuro_san.internals because its first consumers are in this package, and
    neuro_san.message deliberately never imports from neuro_san.internals.
    """

    # Block types that AIMessage.content_blocks merges in from the message's
    # .tool_calls field (or their chunk/invalid variants). These are excluded
    # from the standardized view: they are not message *content*, and today's
    # wire format never carries them, so including them would change the wire
    # output of every existing tool-calling agent.
    TOOL_CALL_BLOCK_TYPES: List[str] = ["tool_call", "tool_call_chunk", "invalid_tool_call"]

    # The response_metadata value that tells langchain the message content
    # already holds standard v1 blocks, so .content_blocks must pass it
    # through instead of re-running a provider translator over it
    # (which would wrap already-standard blocks as "non_standard").
    OUTPUT_VERSION_V1: str = "v1"

    # Standard block types whose payload is data, not conversation text.
    # Providers reject these in assistant-role history, so history
    # projections replace them with a short text reference instead.
    DATA_BLOCK_TYPES: List[str] = ["image", "audio", "video", "file", "text-plain"]

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
        content: Any = source.content if isinstance(source, BaseMessage) else source
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            # Not a legal langchain content shape, but do not crash over it.
            return str(content)

        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text_value: Any = item.get("text")
                # Like BaseMessage.text, a non-string text value contributes
                # nothing (never the literal "None").
                if isinstance(text_value, str):
                    parts.append(text_value)
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
        content: Any = source.content if isinstance(source, BaseMessage) else source
        if content is None:
            return True
        if isinstance(content, str):
            return content.strip() == ""
        if isinstance(content, list):
            return all(ContentUtils._is_blank_block(item) for item in content)
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
        Get the standardized (langchain v1) content-block view of a message.

        Wraps the message's .content_blocks property, which translates
        provider-native content (Anthropic "thinking" dicts, OpenAI Responses
        reasoning items, additional_kwargs reasoning) into standard blocks,
        then:
        - excludes tool-call blocks (see TOOL_CALL_BLOCK_TYPES), and
        - sanitizes the result to be JSON-safe (bytes become base64 strings).

        Call this while the message's response_metadata (model_provider /
        output_version) is still intact - translator selection depends on it.
        Messages lacking model_provider metadata (and Anthropic
        redacted_thinking blocks even with it) standardize provider-native
        shapes as {"type": "non_standard", "value": ...} wrappers: data-
        preserving and JSON-safe, but downstream renderers must expect them.

        :param message: The BaseMessage whose content to standardize
        :return: A JSON-safe list of standard content-block dictionaries
        """
        blocks: List[Dict[str, Any]] = [
            block for block in message.content_blocks
            if block.get("type") not in ContentUtils.TOOL_CALL_BLOCK_TYPES
        ]
        return ContentUtils._to_json_safe(blocks)

    @staticmethod
    def is_trivial(blocks: List[Dict[str, Any]]) -> bool:
        """
        Determine whether a standardized block list carries no more information
        than its flattened text - a single text block with no annotations and
        no extras. Trivial block lists collapse back to plain-string content
        so that existing text-only traffic keeps its exact current shape.

        Policy: provider bookkeeping keys ("id", "index") do NOT make a text
        block non-trivial - such messages are plain strings on today's wire,
        and the collapse deliberately drops those keys to keep that shape.

        :param blocks: A list of standard content-block dictionaries
        :return: True if the list is equivalent to a plain string
        """
        if len(blocks) != 1:
            return False
        block: Dict[str, Any] = blocks[0]
        if block.get("type") != "text":
            return False
        if block.get("annotations") or block.get("extras"):
            return False
        return True

    @staticmethod
    def normalize_content(message: BaseMessage) -> Union[str, List[Dict[str, Any]]]:
        """
        Reduce a message's content to its canonical in-server form:
        plain-string content stays a plain string; block-form content becomes
        the standardized block list - unless it is empty or trivial, in which
        case it collapses to its flattened text so that text-only traffic
        keeps its exact current shape.

        :param message: The BaseMessage whose content to normalize
        :return: A string, or a JSON-safe list of standard block dictionaries
        """
        content: Any = message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list) and all(isinstance(item, str) for item in content):
            # A list of plain strings carries no block structure at all -
            # collapse to text rather than promoting it to a block list.
            return ContentUtils.flatten_to_text(message)
        blocks: List[Dict[str, Any]] = ContentUtils.standard_blocks(message)
        if not blocks or ContentUtils.is_trivial(blocks):
            return ContentUtils.flatten_to_text(message)
        return blocks

    @staticmethod
    def normalize_message(message: BaseMessage) -> BaseMessage:
        """
        Return a copy of the message whose content is normalize_content()'s
        canonical form. When that form is a block list, the copy's
        response_metadata is stamped with output_version="v1" so that any
        later .content_blocks access passes the already-standard blocks
        through instead of re-translating them (which would wrap them
        as "non_standard").

        Intended for COMPLETE messages. Do not use on AIMessageChunks:
        chunk-only shapes (e.g. a tool_call_chunk block living solely in
        chunk content) are not content and would be collapsed away.

        :param message: The BaseMessage to normalize
        :return: The same message instance if nothing changed,
                 otherwise a model_copy with normalized content
        """
        normalized: Union[str, List[Dict[str, Any]]] = ContentUtils.normalize_content(message)
        if isinstance(normalized, str):
            if normalized == message.content:
                return message
            return message.model_copy(update={"content": normalized})

        response_metadata: Dict[str, Any] = dict(message.response_metadata or {})
        response_metadata["output_version"] = ContentUtils.OUTPUT_VERSION_V1
        return message.model_copy(update={
            "content": normalized,
            "response_metadata": response_metadata,
        })

    @staticmethod
    def looks_like_blocks(value: Any) -> bool:
        """
        Determine whether a value is a non-empty list of standard langchain v1
        content-block dictionaries (every element a dict whose "type" is one
        of langchain's KNOWN_BLOCK_TYPES). Does not qualify:
        - provider-native shapes (e.g. Anthropic {"type": "thinking"}),
        - v0-era blocks (marked by a "source_type" key),
        - tool-call blocks (see TOOL_CALL_BLOCK_TYPES) - they are not
          message content, and accepting them inbound would let clients
          inject synthetic tool calls.

        :param value: Any value to inspect
        :return: True if the value can be used as standard block content
        """
        if not isinstance(value, list) or len(value) == 0:
            return False
        for item in value:
            if not isinstance(item, dict):
                return False
            if item.get("type") not in KNOWN_BLOCK_TYPES:
                return False
            if item.get("type") in ContentUtils.TOOL_CALL_BLOCK_TYPES:
                return False
            if "source_type" in item:
                return False
        return True

    # pylint: disable=too-many-return-statements
    @staticmethod
    def blocks_from_chat_message(chat_message: Optional[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """
        Extract langchain v1 content blocks from a neuro-san ChatMessage
        dictionary, if it carries any block-form content.

        Precedence:
        1. A "content_blocks" list of standard blocks is used verbatim.
           A content_blocks value that is present but NOT valid standard
           blocks yields None (fail safe) - it does not fall through to
           mime_data. Note the verbatim path aliases the caller's list;
           callers must not mutate the result.
        2. Otherwise a non-empty "mime_data" list ({"mime_type": ...,
           "mime_bytes": <base64 string>} entries per chat.proto) is mapped to
           data blocks, preceded by a text block for any "text" field.
        3. Otherwise there is no block content.

        :param chat_message: A ChatMessage dictionary
        :return: A list of standard block dictionaries, or None if the
                 message carries no usable block-form content (including
                 when content_blocks or mime_data entries are malformed -
                 callers should fall back to their existing text-only
                 handling)
        """
        if chat_message is None:
            return None

        content_blocks: Any = chat_message.get("content_blocks")
        if content_blocks is not None and content_blocks != []:
            if ContentUtils.looks_like_blocks(content_blocks):
                return content_blocks
            return None

        mime_data: Any = chat_message.get("mime_data")
        if not isinstance(mime_data, list) or len(mime_data) == 0:
            return None

        blocks: List[Dict[str, Any]] = []
        text: Any = chat_message.get("text")
        if isinstance(text, str) and text:
            blocks.append({"type": "text", "text": text})

        for entry in mime_data:
            if not isinstance(entry, dict):
                return None
            mime_type: str = str(entry.get("mime_type") or "")
            mime_bytes: Any = entry.get("mime_bytes")
            if not isinstance(mime_bytes, str) or not mime_bytes or not mime_type:
                return None
            blocks.append(ContentUtils._data_block(mime_type, mime_bytes))

        return blocks

    @staticmethod
    def history_safe_text(source: Union[BaseMessage, str, List[Any], None]) -> str:
        """
        Project content to text that is safe to replay as assistant-role
        conversation history. Text contributes as in flatten_to_text, but
        data-bearing blocks (see DATA_BLOCK_TYPES) are replaced by a short
        "[<type> attachment: <mime_type>]" reference instead of vanishing -
        so an image-only tool result does not become empty history.
        Providers reject raw image/file blocks in assistant-role messages,
        which is why history copies must go through this projection.

        :param source: A BaseMessage, or raw message content
        :return: The history-safe text. Never None.
        """
        content: Any = source.content if isinstance(source, BaseMessage) else source
        if content is None or isinstance(content, str):
            return content or ""
        if not isinstance(content, list):
            return str(content)

        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            block_type: Any = item.get("type")
            if block_type == "text":
                text_value: Any = item.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
            elif block_type in ContentUtils.DATA_BLOCK_TYPES:
                inline_text: Any = item.get("text")
                if isinstance(inline_text, str) and inline_text:
                    # A text-plain block can carry its text inline.
                    parts.append(inline_text)
                else:
                    mime_type: str = str(item.get("mime_type") or "unknown")
                    parts.append(f"[{block_type} attachment: {mime_type}]")
        return "".join(parts)

    @staticmethod
    def _data_block(mime_type: str, base64_str: str) -> Dict[str, Any]:
        """
        Build the standard langchain v1 data block for one MimeData entry.

        :param mime_type: The MIME type of the data
        :param base64_str: The data as a base64 string (never raw bytes)
        :return: A standard data-block dictionary
        """
        if mime_type == "text/plain":
            # PlainTextContentBlock requires its mime_type literal.
            return {"type": "text-plain", "mime_type": "text/plain", "base64": base64_str}

        kind: str = "file"
        for prefix in ("image", "audio", "video"):
            if mime_type.startswith(f"{prefix}/"):
                kind = prefix
                break
        return {"type": kind, "base64": base64_str, "mime_type": mime_type}

    @staticmethod
    def _to_json_safe(value: Any) -> Any:
        """
        Recursively make a value JSON-serializable without dropping data:
        bytes become base64 strings, non-finite floats and unknown objects
        become their string form, tuples and sets become lists, and
        dictionary keys become strings.

        This intentionally differs from ChatMessageConverter.to_json_safe,
        which nulls out bytes - block payloads must survive.

        :param value: Any value to sanitize
        :return: A JSON-serializable equivalent of the value
        """
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)
        if isinstance(value, (bytes, bytearray)):
            return base64.b64encode(bytes(value)).decode("ascii")
        if isinstance(value, dict):
            return {str(key): ContentUtils._to_json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [ContentUtils._to_json_safe(item) for item in value]
        return str(value)
