
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

import copy

from leaf_common.serialization.interface.dictionary_converter import DictionaryConverter

from neuro_san.internals.messages.chat_message_type import ChatMessageType


class ChatMessageConverter(DictionaryConverter):
    """
    Helper class to prepare chat response messages
    for external clients consumption.
    """
    def to_dict(self, obj: object) -> Dict[str, object]:
        """
        :param obj: The object (chat response) to be converted into a dictionary
        :return: chat response dictionary in format expected by clients
        """
        response_dict = copy.deepcopy(obj)
        self.convert(response_dict)
        return response_dict

    def convert(self, response_dict: Dict[str, Any]):
        """
        Convert chat response message to a format expected by external clients:
        :param response_dict: chat response message to be sent out
        """
        # Ensure that we return ChatMessageType as a string in output json
        message_dict: Dict[str, Any] = response_dict.get('response', None)
        if message_dict is not None:
            self.convert_message(message_dict)

    def convert_message(self, message_dict: Dict[str, Any]):
        """
        Convert chat message to a format expected by external clients:
        :param message_dict: chat message to process
        """
        # Ensure that we return ChatMessageType as a string in output json
        response_type = message_dict.get('type', None)
        if response_type is not None:
            message_dict['type'] =\
                ChatMessageType.from_response_type(response_type).name
        chat_context: Dict[str, Any] = message_dict.get('chat_context', None)
        if chat_context is not None:
            for chat_history in chat_context.get("chat_histories", []):
                for chat_message in chat_history.get("messages", []):
                    self.convert_message(chat_message)

    def from_dict(self, obj_dict: Dict[str, object]) -> object:
        """
        :param obj_dict: The data-only dictionary to be converted into an object
        :return: An object instance created from the given dictionary.
                If obj_dict is None, the returned object should also be None.
                If obj_dict is not the correct type, it is also reasonable
                to return None.
        """
        raise NotImplementedError
