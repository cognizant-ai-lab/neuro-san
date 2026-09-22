
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
from __future__ import annotations

from typing import Type
from typing import Union

from langchain_core.messages.base import BaseMessage

from neuro_san.message.types.chat_message_type import ChatMessageType
from neuro_san.message.types.chat_message_type import CHAT_MESSAGE_TYPE_TO_STRING
from neuro_san.message.types.chat_message_type import MESSAGE_TYPE_TO_CHAT_MESSAGE_TYPE


class ChatMessageTypeUtil:
    """
    Static utility class for ChatMessageType.
    """
    @staticmethod
    def from_message(base_message: BaseMessage) -> ChatMessageType:
        """
        :param base_message: A base message instance
        :return: The ChatMessageType corresponding to the base_message
        """
        base_message_type: Type[BaseMessage] = type(base_message)
        chat_message_type: ChatMessageType = \
            MESSAGE_TYPE_TO_CHAT_MESSAGE_TYPE.get(base_message_type, ChatMessageType.UNKNOWN_MESSAGE_TYPE)
        return chat_message_type

    @staticmethod
    def from_response_type(response_type: Union[str, ChatMessageType]) -> ChatMessageType:
        """
        :param response_type: A type from a response instance
        :return: The ChatMessageType corresponding to the base_message
        """
        message_type: ChatMessageType = ChatMessageType.UNKNOWN_MESSAGE_TYPE

        if response_type is None:
            # Return early
            return message_type

        if isinstance(response_type, ChatMessageType):
            return response_type

        if isinstance(response_type, int):
            return ChatMessageType(response_type)

        try:
            # Normal case: We have a 1:1 mapping of ChatMessageType to what is in grpc def
            message_type = ChatMessageType[response_type]
        except KeyError as exception:
            raise ValueError(f"Got message type {response_type} (type {response_type.__class__.__name__})."
                             " Are ChatMessageType and chat.proto out of sync?") from exception
        return message_type

    @staticmethod
    def to_string(chat_message_type: ChatMessageType) -> str:
        """
        :param chat_message_type: A ChatMessageType instance
        :return: A string corresponding to the chat_message_type
        """
        message_type_str: str = CHAT_MESSAGE_TYPE_TO_STRING.get(chat_message_type)
        if message_type_str is None:
            message_type_str = CHAT_MESSAGE_TYPE_TO_STRING.get(ChatMessageType.UNKNOWN_MESSAGE_TYPE)
        return message_type_str
