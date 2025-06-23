
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
from typing import List

from neuro_san.message_processing.answer_message_processor import AnswerMessageProcessor
from neuro_san.message_processing.chat_context_message_processor import ChatContextMessageProcessor
from neuro_san.message_processing.composite_message_processor import CompositeMessageProcessor
from neuro_san.message_processing.message_processor import MessageProcessor


class BasicMessageProcessor(CompositeMessageProcessor):
    """
    A CompositeMessageProcessor that provides the most basic operations
    that most everyone needs.
    """

    def __init__(self, message_processors: List[MessageProcessor] = None):
        """
        Constructor

        :param message_processors: An ordered List of additional MessageProcessors with which
                     this instance will process messages
        """
        super().__init__(message_processors)

        self.answer = AnswerMessageProcessor()
        self.chat_context = ChatContextMessageProcessor()

        # These always go first because they should never be blocked
        self.message_processors.insert(0, self.chat_context)
        self.message_processors.insert(0, self.answer)

    def get_answer(self) -> str:
        """
        :return: The final answer from the agent session interaction
        """
        return self.answer.get_answer()

    def get_answer_origin(self) -> List[Dict[str, Any]]:
        """
        :return: The origin of the final answer from the agent session interaction
        """
        return self.answer.get_answer_origin()

    def get_sly_data(self) -> Dict[str, Any]:
        """
        :return: Any sly_data that was returned
        """
        return self.chat_context.get_sly_data()

    def get_chat_context(self) -> Dict[str, Any]:
        """
        :return: The chat_context discovered from the agent session interaction
                Empty dictionaries or None values simply start a new conversation.
        """
        return self.chat_context.get_chat_context()

    def get_structure(self) -> Dict[str, Any]:
        """
        :return: Any dictionary structure that was contained within the final answer
                 from the agent session interaction, if such a specific breakout was desired.
        """
        return self.answer.get_structure()
