
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

from neuro_san.message.filters.message_filter import MessageFilter
from neuro_san.message.types.chat_message_type import ChatMessageType


class ChatContextMessageFilter(MessageFilter):
    """
    MessageFilter implementation for a message with "the chat_context" in it.
    """

    def allow_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType) -> bool:
        """
        Determine whether to allow the message through.

        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        :return: True if the message should be allowed through to the client. False otherwise.
        """
        if message_type != ChatMessageType.AGENT_FRAMEWORK:
            # Final chat_contexts are only ever AI Messages
            return False

        if chat_message_dict.get("chat_context") is None:
            return False

        # Meets all our criteria. Let it through.
        return True
