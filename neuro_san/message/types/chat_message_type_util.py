
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

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.system import SystemMessage
from langchain_core.messages.tool import ToolMessage

from neuro_san.message.types.agent_framework_message import AgentFrameworkMessage
from neuro_san.message.types.agent_message import AgentMessage
from neuro_san.message.types.agent_progress_message import AgentProgressMessage
from neuro_san.message.types.agent_tool_result_message import AgentToolResultMessage
from neuro_san.message.types.chat_message_type import ChatMessageType
from neuro_san.message.types.chat_message_type import CHAT_MESSAGE_TYPE_TO_STRING


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
        # Compare exact types rather than isinstance(), as AgentToolResultMessage
        # derives from AIMessage and subclasses like AIMessageChunk are not mapped.
        # These need to match chat.proto.
        base_message_type: Type[BaseMessage] = type(base_message)
        chat_message_type: ChatMessageType = ChatMessageType.UNKNOWN_MESSAGE_TYPE
        if base_message_type is SystemMessage:
            chat_message_type = ChatMessageType.SYSTEM
        elif base_message_type is HumanMessage:
            chat_message_type = ChatMessageType.HUMAN
        elif base_message_type is AIMessage:
            chat_message_type = ChatMessageType.AI
        elif base_message_type is ToolMessage:
            # A tool's answer to a tool call made by an AI message. On the wire its tool_call_info
            # carries the id of that call, which is what tells it apart from an AgentToolResultMessage.
            chat_message_type = ChatMessageType.AGENT_TOOL_RESULT
        elif base_message_type is AgentMessage:
            chat_message_type = ChatMessageType.AGENT
        elif base_message_type is AgentFrameworkMessage:
            chat_message_type = ChatMessageType.AGENT_FRAMEWORK
        elif base_message_type is AgentToolResultMessage:
            chat_message_type = ChatMessageType.AGENT_TOOL_RESULT
        elif base_message_type is AgentProgressMessage:
            chat_message_type = ChatMessageType.AGENT_PROGRESS
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
