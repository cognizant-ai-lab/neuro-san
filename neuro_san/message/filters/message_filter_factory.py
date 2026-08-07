
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
from typing import Type

from neuro_san.message.filters.maximal_message_filter import MaximalMessageFilter
from neuro_san.message.filters.message_filter import MessageFilter
from neuro_san.message.filters.minimal_message_filter import MinimalMessageFilter

TYPE_TO_MESSAGE_FILTER_CLASS: Dict[Any, Type[MessageFilter]] = {
    0:  MinimalMessageFilter,
    1:  MinimalMessageFilter,
    2:  MaximalMessageFilter,

    "UNKNOWN":  MinimalMessageFilter,
    "MINIMAL":  MinimalMessageFilter,
    "MAXIMAL":  MaximalMessageFilter,
}


class MessageFilterFactory:
    """
    Class for creating MessageFilters
    """

    @staticmethod
    def create_message_filter(chat_filter: Dict[str, Any]) -> MessageFilter:
        """
        :param chat_filter: The ChatFilter dictionary to process.
        :return: A MessageFilter that corresponds to the contents
        """

        # For now the default is MAXIMAL simply to emulate current behavior.
        # After the ChatFilter API gets released this will eventually change to "MINIMAL".
        default: str = "MINIMAL"
        chat_filter_type: Any = default

        # Get what was in the request
        if chat_filter is not None:
            chat_filter_type = chat_filter.get("chat_filter_type", chat_filter_type)

        # Change strings so they are suitable for lookup
        if isinstance(chat_filter_type, str):
            chat_filter_type = chat_filter_type.upper()

        chat_filter_class: MessageFilter = TYPE_TO_MESSAGE_FILTER_CLASS.get(chat_filter_type)
        if chat_filter_class is None:
            chat_filter_class = TYPE_TO_MESSAGE_FILTER_CLASS.get(default)

        # Instantiate the class and return
        message_filter: MessageFilter = chat_filter_class()
        return message_filter
