
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

from enum import IntEnum
from typing import Dict
from typing import Type

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.system import SystemMessage

from neuro_san.message.types.agent_framework_message import AgentFrameworkMessage
from neuro_san.message.types.agent_message import AgentMessage
from neuro_san.message.types.agent_progress_message import AgentProgressMessage
from neuro_san.message.types.agent_tool_result_message import AgentToolResultMessage


class ChatMessageType(IntEnum):
    """
    Python enum to mimic protobufs for chat.ChatMessageType without dragging in all of gRPC.
    These all need to match what is defined in chat.proto
    """
    UNKNOWN_MESSAGE_TYPE: int = 0
    SYSTEM: int = 1
    HUMAN: int = 2
    AI: int = 4

    AGENT: int = 100
    AGENT_FRAMEWORK: int = 101
    AGENT_TOOL_RESULT: int = 103
    AGENT_PROGRESS: int = 104

    # Adding something? Don't forget to update the maps below.


# Convenience mappings going between constants and class types
_MESSAGE_TYPE_TO_CHAT_MESSAGE_TYPE: Dict[Type[BaseMessage], ChatMessageType] = {
    # Needs to match chat.proto
    SystemMessage: ChatMessageType.SYSTEM,
    HumanMessage: ChatMessageType.HUMAN,
    AIMessage: ChatMessageType.AI,

    AgentMessage: ChatMessageType.AGENT,
    AgentFrameworkMessage: ChatMessageType.AGENT_FRAMEWORK,
    AgentToolResultMessage: ChatMessageType.AGENT_TOOL_RESULT,
    AgentProgressMessage: ChatMessageType.AGENT_PROGRESS,
}

_CHAT_MESSAGE_TYPE_TO_STRING: Dict[ChatMessageType, str] = {

    ChatMessageType.UNKNOWN_MESSAGE_TYPE: "UNKNOWN",

    ChatMessageType.SYSTEM: "SYSTEM",
    ChatMessageType.HUMAN: "HUMAN",
    ChatMessageType.AI: "AI",

    ChatMessageType.AGENT: "AGENT",
    ChatMessageType.AGENT_FRAMEWORK: "AGENT_FRAMEWORK",
    ChatMessageType.AGENT_TOOL_RESULT: "AGENT_TOOL_RESULT",
    ChatMessageType.AGENT_PROGRESS: "AGENT_PROGRESS",
}
