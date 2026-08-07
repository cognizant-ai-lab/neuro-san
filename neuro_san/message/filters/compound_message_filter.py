
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


class CompoundMessageFilter(MessageFilter):
    """
    A MessageFilter implementation that can service multiple other MessageFilter instances
    """

    def __init__(self, filters: List[MessageFilter] = None):
        """
        Constructor

        :param filters: A List of MessageFilter instances to simultaneously service
        """
        self.filters: List[MessageFilter] = filters
        if self.filters is None:
            self.filters = []

    def allow_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType) -> bool:
        """
        Determine whether to allow the message through.
        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        :return: True if the message should be allowed through to the client. False otherwise.
        """
        # If any one filter says to let a message through, then let it through.
        for one_filter in self.filters:
            if one_filter.allow_message(chat_message_dict, message_type):
                return True

        # Nobody wanted it.
        return False

    def add_message_filter(self, message_filter: MessageFilter):
        """
        Adds a message_filter to the list
        :param message_filter: A MessageFilter instance to service
        """
        self.filters.append(message_filter)
