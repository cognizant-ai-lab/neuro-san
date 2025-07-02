
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT
from typing import Any
from typing import Dict
from typing import List

from neuro_san.internals.filters.message_filter import MessageFilter
from neuro_san.internals.messages.chat_message_type import ChatMessageType


class AnswerMessageFilter(MessageFilter):
    """
    MessageFilter implementation for a message with "the answer" in it.
    """

    def allow_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType) -> bool:
        """
        Determine whether to allow the message through.

        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        :return: True if the message should be allowed through to the client. False otherwise.
        """
        if message_type not in (ChatMessageType.AI, ChatMessageType.AGENT_FRAMEWORK):
            # Final answers are only ever AI or AgentFramework Messages
            return False

        origin: List[Dict[str, Any]] = chat_message_dict.get("origin")
        if origin is not None and len(origin) > 1:
            # Final answers only come from the FrontMan,
            # whose origin length is the only one of length 1.
            return False

        text: str = chat_message_dict.get("text")
        structure: Dict[str, Any] = chat_message_dict.get("structure")
        if text is None and structure is None:
            # Final answers need to be text or structure.
            # There might be more options in the future.
            return False

        # Meets all our criteria. Let it through.
        return True
