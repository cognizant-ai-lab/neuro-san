
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
    AGENT_PROGRESS = 104

    # Adding something? Don't forget to update the map below
    # and ChatMessageTypeUtil.from_message().


CHAT_MESSAGE_TYPE_TO_STRING: Dict[ChatMessageType, str] = {

    ChatMessageType.UNKNOWN_MESSAGE_TYPE: "UNKNOWN",

    ChatMessageType.SYSTEM: "SYSTEM",
    ChatMessageType.HUMAN: "HUMAN",
    ChatMessageType.AI: "AI",

    ChatMessageType.AGENT: "AGENT",
    ChatMessageType.AGENT_FRAMEWORK: "AGENT_FRAMEWORK",
    ChatMessageType.AGENT_TOOL_RESULT: "AGENT_TOOL_RESULT",
    ChatMessageType.AGENT_PROGRESS: "AGENT_PROGRESS",
}
