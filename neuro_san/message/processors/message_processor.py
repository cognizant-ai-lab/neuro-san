
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

from neuro_san.message.types.chat_message_type import ChatMessageType


class MessageProcessor:
    """
    An interface for processing a single message.
    """

    def reset(self):
        """
        Resets any previously accumulated state
        """

    def should_block_downstream_processing(self, chat_message_dict: Dict[str, Any],
                                           message_type: ChatMessageType) -> bool:
        """
        :param chat_message_dict: The ChatMessage dictionary to consider.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        :return: True if the given message should be blocked from further downstream
                processing.  False otherwise (the default).
        """
        _ = chat_message_dict, message_type
        return False

    def process_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType):
        """
        Process the message.
        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        """
        raise NotImplementedError

    async def async_process_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType):
        """
        Process the message asynchronously.
        By default, this simply calls the synchronous version.

        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        """
        self.process_message(chat_message_dict, message_type)

    def process_messages(self, chat_message_dicts: List[Dict[str, Any]]):
        """
        Convenience method for processing lists of messages.
        :param chat_message_dicts: The messages to process.
        """
        for message in chat_message_dicts:
            message_type: ChatMessageType = message.get("type")
            self.process_message(message, message_type)

    async def async_process_messages(self, chat_message_dicts: List[Dict[str, Any]]):
        """
        Convenience method for asynchronouslt processing lists of messages.
        :param chat_message_dicts: The messages to process.
        """
        for message in chat_message_dicts:
            message_type: ChatMessageType = message.get("type")
            await self.async_process_message(message, message_type)
