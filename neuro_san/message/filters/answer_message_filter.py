
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

from neuro_san.message.filters.message_filter import MessageFilter
from neuro_san.message.types.chat_message_type import ChatMessageType


class AnswerMessageFilter(MessageFilter):
    """
    MessageFilter implementation for a message with "the answer" in it.
    """

    def allow_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType) -> bool:
        """
        Determine whether to allow the message through.

        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        :return: True if the message should be allowed through to the client. False otherwise.
        """
        if message_type not in (ChatMessageType.AI, ChatMessageType.AGENT_FRAMEWORK):
            # Final answers are only ever AI or AgentFramework Messages
            return False

        origin: List[Dict[str, Any]] = chat_message_dict.get("origin")
        if origin is not None and len(origin) > 1:
            # Final answers only come from the FrontMan,
            # whose origin length is the only one of length 1.
            return False

        text: str = chat_message_dict.get("text")
        structure: Dict[str, Any] = chat_message_dict.get("structure")
        if text is None and structure is None:
            # Final answers need to be text or structure.
            # There might be more options in the future.
            return False

        # Meets all our criteria. Let it through.
        return True
