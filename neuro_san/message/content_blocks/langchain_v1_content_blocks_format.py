
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
    DATA_BLOCK_TYPES: List[str] = ["image", "audio", "video", "file", "text-plain"]

    @override
    def get_name(self) -> str:
        """
        Give the name this format has on the wire.

        :return: The "format" value that names this format on the wire
        """
        return self.NAME

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
        if item_type not in KNOWN_BLOCK_TYPES:
            return False
        if item_type in self.TOOL_CALL_BLOCK_TYPES:
            return False
        if "source_type" in item_dict:
            return False
        return True

    @override
    def restore_blocks(self, blocks: List[Any]) -> List[Dict[str, Any]]:
        """
        Keep the blocks a model can be given again: text blocks with a text
        string (every other key, such as an OpenAI "phase", stays with them)
        and reasoning blocks that carry something. Data blocks are dropped
        because attachments are not sent to a model yet. Tool-call blocks,
        blocks no provider takes as input (see NOT_INPUT_BLOCK_TYPES) and
        anything malformed are dropped too. Whether a kept reasoning block
        still pairs with its provider state is for the provider to judge.

        :param blocks: The "blocks" list of an inbound content_blocks wrapper
        :return: The surviving blocks, the same dictionaries, in order
        """
        kept: List[Dict[str, Any]] = []
        # Keep each block a model can be given again, in order.
        item: Any = None
        for item in blocks:
            block: Optional[Dict[str, Any]] = self.restore_block(item)
            if block is not None:
                kept.append(block)
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
        if block_type in self.NOT_INPUT_BLOCK_TYPES:
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
