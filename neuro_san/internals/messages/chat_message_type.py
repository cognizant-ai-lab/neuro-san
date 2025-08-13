
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
from __future__ import annotations

from enum import IntEnum
from typing import Dict
from typing import Type
from typing import Union

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.system import SystemMessage

from neuro_san.internals.messages.agent_framework_message import AgentFrameworkMessage
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.messages.agent_tool_result_message import AgentToolResultMessage


class ChatMessageType(IntEnum):
    """
    Python enum to mimic protobufs for chat.ChatMessageType without dragging in all of gRPC.
    These all need to match what is defined in chat.proto
    """
    UNKNOWN_MESSAGE_TYPE = 0
    SYSTEM = 1
    HUMAN = 2
    AI = 4

    AGENT = 100
    AGENT_FRAMEWORK = 101
    AGENT_TOOL_RESULT = 103

    # Adding something? Don't forget to update the maps below.

    @classmethod
    def from_message(cls, base_message: BaseMessage) -> ChatMessageType:
        """
        :param base_message: A base message instance
        :return: The ChatMessageType corresponding to the base_message
        """
        base_message_type: Type[BaseMessage] = type(base_message)
        chat_message_type: ChatMessageType = \
            _MESSAGE_TYPE_TO_CHAT_MESSAGE_TYPE.get(base_message_type, cls.UNKNOWN_MESSAGE_TYPE)
        return chat_message_type

    @classmethod
    def from_response_type(cls, response_type: Union[str, ChatMessageType]) -> ChatMessageType:
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

    @classmethod
    def message_to_role(cls, base_message: BaseMessage) -> str:
        """
        This role stuff will be removed when the Logs() API is removed,
        as the ChatMessageType and grpc definitions make it redundant.

        :param base_message: A base message instance
        :return: The role string corresponding to the base_message
        """
        base_message_type: Type[BaseMessage] = type(base_message)
        role: str = _MESSAGE_TYPE_TO_ROLE.get(base_message_type)
        return role

    @classmethod
    def to_string(cls, chat_message_type: ChatMessageType) -> str:
        """
        :param chat_message_type: A ChatMessageType instance
        :return: A string corresponding to the chat_message_type
        """
        message_type_str: str = _CHAT_MESSAGE_TYPE_TO_STRING.get(chat_message_type)
        if message_type_str is None:
            message_type_str = _CHAT_MESSAGE_TYPE_TO_STRING.get(cls.UNKNOWN_MESSAGE_TYPE)
        return message_type_str


# Convenience mappings going between constants and class types
_MESSAGE_TYPE_TO_CHAT_MESSAGE_TYPE: Dict[Type[BaseMessage], ChatMessageType] = {
    # Needs to match chat.proto
    SystemMessage: ChatMessageType.SYSTEM,
    HumanMessage: ChatMessageType.HUMAN,
    AIMessage: ChatMessageType.AI,

    AgentMessage: ChatMessageType.AGENT,
    AgentFrameworkMessage: ChatMessageType.AGENT_FRAMEWORK,
    AgentToolResultMessage: ChatMessageType.AGENT_TOOL_RESULT,
}

_MESSAGE_TYPE_TO_ROLE: Dict[Type[BaseMessage], str] = {
    AIMessage: "assistant",
    HumanMessage: "user",
    SystemMessage: "system",
    AgentMessage: "agent",
    AgentFrameworkMessage: "agent-framework",
    AgentToolResultMessage: "agent-tool-result",
}

_CHAT_MESSAGE_TYPE_TO_STRING: Dict[ChatMessageType, str] = {

    ChatMessageType.UNKNOWN_MESSAGE_TYPE: "UNKNOWN",

    ChatMessageType.SYSTEM: "SYSTEM",
    ChatMessageType.HUMAN: "HUMAN",
    ChatMessageType.AI: "AI",

    ChatMessageType.AGENT: "AGENT",
    ChatMessageType.AGENT_FRAMEWORK: "AGENT_FRAMEWORK",
    ChatMessageType.AGENT_TOOL_RESULT: "AGENT_TOOL_RESULT",
}
