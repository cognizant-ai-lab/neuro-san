
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
from typing import Union

from neuro_san.message.filters.answer_message_filter import AnswerMessageFilter
from neuro_san.message.parsers.structure.first_available_structure_parser import FirstAvailableStructureParser
from neuro_san.message.processors.message_processor import MessageProcessor
from neuro_san.message.types.chat_message_type import ChatMessageType


class AnswerMessageProcessor(MessageProcessor):
    """
    Implementation of the MessageProcessor that looks for "the answer"
    of the chat session.
    """

    def __init__(self, structure_formats: Union[str, List[str]] = None):
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
        self.answer: str = None
        self.structure: Dict[str, Any] = None
        self.answer_origin: List[Dict[str, Any]] = None
        self.filter: AnswerMessageFilter = AnswerMessageFilter()

        # Only deal with non-empy lists of strings internally
        self.structure_formats: List[str] = structure_formats
        if self.structure_formats is not None:
            if isinstance(self.structure_formats, str):
                self.structure_formats = [self.structure_formats]
        else:
            self.structure_formats = []

        if not isinstance(self.structure_formats, List):
            raise ValueError(f"Value '{structure_formats}' must be a string, a list of strings, or None")

    def get_answer(self) -> str:
        """
        :return: The final answer from the agent session interaction
        """
        return self.answer

    def get_answer_origin(self) -> List[Dict[str, Any]]:
        """
        :return: The origin of the final answer from the agent session interaction
        """
        return self.answer_origin

    def get_structure(self) -> Dict[str, Any]:
        """
        :return: Any dictionary structure that was contained within the final answer
                 from the agent session interaction, if such a specific breakout was desired.
        """
        return self.structure

    def reset(self):
        """
        Resets any previously accumulated state
        """
        self.answer = None
        self.structure = None
        self.answer_origin = None

    def process_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType):
        """
        Process the message.
        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        """
        if not self.filter.allow_message(chat_message_dict, message_type):
            # Does not pass the criteria for a message holding a final answer
            return

        origin: List[Dict[str, Any]] = chat_message_dict.get("origin")
        text: str = chat_message_dict.get("text")
        structure: Dict[str, Any] = chat_message_dict.get("structure")

        # Record what we got.
        # We might get another as we go along, but the last message in the stream
        # meeting the criteria above is our final answer.
        if text is not None:
            self.answer = text
        if origin is not None:
            self.answer_origin = origin
        if structure is not None:
            self.structure = structure

        if structure is None and text is not None:
            # Parse structure from the first available format in the answer content
            structure_parser = FirstAvailableStructureParser(self.structure_formats)
            self.structure = structure_parser.parse_structure(text)
            if self.structure is not None:
                self.answer = structure_parser.get_remainder()
