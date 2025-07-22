
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


class TokenAccountingMessageFilter(MessageFilter):
    """
    MessageFilter implementation for a message with token accounting in it.
    """

    def allow_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType) -> bool:
        """
        Determine whether to allow the message through.

        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        :return: True if the message should be allowed through to the client. False otherwise.
        """
        if message_type != ChatMessageType.AGENT:
            # Token accounting information only ever come from Agent Messages
            return False

        origin: List[Dict[str, Any]] = chat_message_dict.get("origin")
        if origin is not None and len(origin) > 1:
            # Final token accounting only come from the FrontMan,
            # whose origin length is the only one of length 1.
            return False

        structure: Dict[str, Any] = chat_message_dict.get("structure")
        if structure is None:
            # Final token accounting needs to come from structure.
            return False

        if structure.get("total_tokens") is None:
            # Final token accounting answers need to have a total_tokens key in the structure dict
            return False

        # Meets all our criteria. Let it through.
        return True
