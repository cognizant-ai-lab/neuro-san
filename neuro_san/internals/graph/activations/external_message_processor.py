
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

from copy import copy

from langchain_core.messages.base import BaseMessage

from neuro_san.internals.journals.originating_journal import OriginatingJournal
from neuro_san.internals.messages.base_message_dictionary_converter import BaseMessageDictionaryConverter
from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.message_processing.message_processor import MessageProcessor


class ExternalMessageProcessor(MessageProcessor):
    """
    MessageProcessor implementation for handling messages from an external agent network.
    """

    def __init__(self, journal: OriginatingJournal):
        """
        Constructor

        :param journal: The OriginatingJournal through which messages from
                    the external agent are passed.
        """
        self.journal: OriginatingJournal = journal

    async def async_process_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType):
        """
        Process the message asynchronously.
        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        """
        message_origin: List[Dict[str, Any]] = chat_message_dict.get("origin")
        if message_origin is None:
            return

        # Append the origin information from the external agent to our own
        origin: List[Dict[str, Any]] = copy(self.journal.get_origin())
        origin.extend(message_origin)

        # Send the message to the client with deepened origin information
        converter = BaseMessageDictionaryConverter(langchain_only=False)
        message: BaseMessage = converter.from_dict(chat_message_dict)
        await self.journal.write_message(message, origin=origin)

    def process_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType):
        """
        Process the message.
        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        """
        # We don't implement this because we need to do so asynchronously
        raise NotImplementedError
