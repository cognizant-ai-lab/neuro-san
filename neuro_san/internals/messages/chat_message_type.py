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
from langchain_core.messages.tool import ToolMessage

from neuro_san.internals.messages.agent_framework_message import AgentFrameworkMessage
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.messages.legacy_logs_message import LegacyLogsMessage


class ChatMessageType(IntEnum):
    """
    Python enum to mimic protobufs for chat.ChatMessageType without dragging in all of gRPC.
    These all need to match what is defined in chat.proto
    """
    UNKNOWN_MESSAGE_TYPE = 0
    SYSTEM = 1
    HUMAN = 2
    TOOL = 3
    AI = 4

    AGENT = 100
    AGENT_FRAMEWORK = 101
    LEGACY_LOGS = 102

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


# Convenience mappings going between constants and class types
_MESSAGE_TYPE_TO_CHAT_MESSAGE_TYPE: Dict[Type[BaseMessage], ChatMessageType] = {
    # Needs to match chat.proto
    SystemMessage: ChatMessageType.SYSTEM,
    HumanMessage: ChatMessageType.HUMAN,
    ToolMessage: ChatMessageType.TOOL,
    AIMessage: ChatMessageType.AI,

    AgentMessage: ChatMessageType.AGENT,
    AgentFrameworkMessage: ChatMessageType.AGENT_FRAMEWORK,
    LegacyLogsMessage: ChatMessageType.LEGACY_LOGS,
}

_MESSAGE_TYPE_TO_ROLE: Dict[Type[BaseMessage], str] = {
    AIMessage: "assistant",
    HumanMessage: "user",
    ToolMessage: "tool",
    SystemMessage: "system",
    AgentMessage: "agent",
    AgentFrameworkMessage: "agent-framework",
    LegacyLogsMessage: "legacy-logs",
}
