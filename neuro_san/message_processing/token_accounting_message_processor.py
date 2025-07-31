
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
from typing import Any
from typing import Dict

from neuro_san.internals.filters.token_accounting_message_filter import TokenAccountingMessageFilter
from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.message_processing.message_processor import MessageProcessor


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
