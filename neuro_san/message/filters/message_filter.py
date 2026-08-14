
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

from neuro_san.message.types.chat_message_type import ChatMessageType


class MessageFilter:
    """
    An interface for filtering a single message.
    """

    def allow(self, chat_message_dict: Dict[str, Any]) -> bool:
        """
        Determine whether to allow the message through.
        This is the main entry point for most clients.
        """
        message_type: ChatMessageType = self.get_message_type(chat_message_dict)
        return self.allow_message(chat_message_dict, message_type)

    @staticmethod
    def get_message_type(chat_message_dict: Dict[str, Any]) -> ChatMessageType:
        """
        Convert the message type in the ChatMessage dictionary to the enum we want to work with
        :param chat_message_dict: The ChatMessage dictionary to consider.
        :return: The ChatMessageType of the chat_message_dict
        """
        response_type: str = chat_message_dict.get("type")
        message_type: ChatMessageType = ChatMessageType.from_response_type(response_type)
        return message_type

    def allow_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType) -> bool:
        """
        Determine whether to allow the message through.
        This is what subclasses should implement.
        MessageProcessors also call this interface directly.

        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        :return: True if the message should be allowed through to the client. False otherwise.
        """
        raise NotImplementedError
