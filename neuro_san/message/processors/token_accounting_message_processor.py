
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

from neuro_san.message.filters.token_accounting_message_filter import TokenAccountingMessageFilter
from neuro_san.message.processors.message_processor import MessageProcessor
from neuro_san.message.types.chat_message_type import ChatMessageType


class TokenAccountingMessageProcessor(MessageProcessor):
    """
    Implementation of the MessageProcessor that looks for the final token accouting
    of the chat session.
    """

    def __init__(self):
        """
        Constructor

        :param structure_formats: Optional string or list of strings telling us to look for
                    specific formats within the text of the final answer to separate out
                    in a common way so that clients do not have to reinvent this wheel over
                    and over again.

                    Valid values are:
                        "json" - look for JSON in the message content as structure to report.

                    By default this is None, implying that such parsing is bypassed.
        """
        self.token_accounting: Dict[str, Any] = None
        self.filter: TokenAccountingMessageFilter = TokenAccountingMessageFilter()

    def get_token_accounting(self) -> Dict[str, Any]:
        """
        :return: The final token accounting from the agent session interaction
        """
        return self.token_accounting

    def reset(self):
        """
        Resets any previously accumulated state
        """
        self.token_accounting = None

    def process_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType):
        """
        Process the message.
        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        """
        if not self.filter.allow_message(chat_message_dict, message_type):
            # Does not pass the criteria for a message holding a final answer
            return

        structure: Dict[str, Any] = chat_message_dict.get("structure")

        # Record what we got.
        # We might get another as we go along, but the last message in the stream
        # meeting the criteria above is our final answer.
        if structure is not None:
            self.token_accounting = structure
