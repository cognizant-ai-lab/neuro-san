
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

from abc import abstractmethod

from langchain_core.messages.base import BaseMessage
from leaf_common.utils.interface import interface


@interface
class ContentBlocksFormat:
    """
    An interface for one format of the blocks a ChatMessage carries in
    content_blocks (see ContentBlocks in chat.proto).

    The wrapper's "format" string names the schema of its "blocks" list.
    Everything the server does that depends on that schema goes through an
    implementation of this interface, found in ContentBlocksFormatRegistry
    by the wrapper's name or by the mark a message carries, so that a new
    format is a new class and not a change to the places that use blocks.

    A format's blocks are LangChain message content: the server stores the
    blocks that blocks_of and restore_blocks return as BaseMessage.content,
    and "flattened text" means what BaseMessage.text reports for that
    content (see ContentUtils.flatten_to_text).
    """

    @abstractmethod
    def get_name(self) -> str:
        """
        Give the name this format has on the wire.

        :return: The "format" value that names this format on the wire
        """
        raise NotImplementedError

    @abstractmethod
    def is_format_of(self, message: BaseMessage) -> bool:
        """
        Determine whether a message's content is already marked as blocks
        of this format (see response_metadata_for).

        :param message: The BaseMessage to inspect
        :return: True if the message carries this format's mark
        """
        raise NotImplementedError

    @abstractmethod
    def is_block_list(self, value: Any) -> bool:
        """
        Determine whether a value is a non-empty list of blocks in this
        format that can be used as message content.

        :param value: Any value to inspect
        :return: True if every element is a block this format accepts as content
        """
        raise NotImplementedError

    @abstractmethod
    def blocks_of(self, message: BaseMessage) -> List[Dict[str, Any]]:
        """
        Give this format's block view of a LangChain message, for the
        outbound wire. The blocks are not made JSON-safe here; the caller
        does that.

        :param message: The BaseMessage whose content to view as blocks
        :return: The content blocks of the message in this format, in order
        """
        raise NotImplementedError

    @abstractmethod
    def is_trivial(self, blocks: List[Dict[str, Any]]) -> bool:
        """
        Determine whether a block list says nothing beyond its flattened
        text, so that it can collapse to a plain string.

        :param blocks: A list of blocks in this format
        :return: True if the list is equivalent to a plain string
        """
        raise NotImplementedError

    @abstractmethod
    def restore_blocks(self, blocks: List[Any], for_chat_history: bool = False) -> List[Dict[str, Any]]:
        """
        Keep the blocks of an inbound list that are well-formed and that a
        model can be given again as message content, and drop the rest.

        :param blocks: The "blocks" list of an inbound content_blocks wrapper
        :param for_chat_history: True when the blocks will be replayed to a
                model as chat history, which also drops what such history
                cannot take yet. A format with nothing that chat history
                cannot take returns the same list for both values.
        :return: The blocks to use as message content, in order. Can be empty.
        """
        raise NotImplementedError

    @abstractmethod
    def history_safe_text(self, content: List[Any]) -> str:
        """
        Project list content to text that is safe to replay as
        assistant-role history. Data blocks become a short text reference
        instead of vanishing.

        :param content: A message's list content: strings and/or blocks
        :return: The history-safe text. Never None.
        """
        raise NotImplementedError

    @abstractmethod
    def text_block(self, text: str) -> Dict[str, Any]:
        """
        Build a text block of this format.

        :param text: The text the block carries
        :return: A text block dictionary
        """
        raise NotImplementedError

    @abstractmethod
    def data_block(self, mime_type: str, base64_str: str) -> Dict[str, Any]:
        """
        Build a data block of this format for one MimeData entry
        (see chat.proto).

        :param mime_type: The MIME type of the data
        :param base64_str: The data as a base64 string (never raw bytes)
        :return: A data block dictionary
        """
        raise NotImplementedError

    @abstractmethod
    def response_metadata_for(self, message: BaseMessage) -> Dict[str, Any]:
        """
        Build the response_metadata a message must carry when its content is
        blocks of this format: a copy of the message's own, marked so that
        the content is recognized as this format's blocks already and is not
        derived again.

        :param message: The BaseMessage whose response_metadata to start from
        :return: A new response_metadata dictionary
        """
        raise NotImplementedError
