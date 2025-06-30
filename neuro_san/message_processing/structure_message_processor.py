
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
from typing import Union

from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.internals.parsers.structure.first_available_structure_parser \
    import FirstAvailableStructureParser
from neuro_san.message_processing.message_processor import MessageProcessor


class StructureMessageProcessor(MessageProcessor):
    """
    Implementation of the MessageProcessor that looks for
    structure information in chat text and extracts structure based on
    the format list that was passed into the constructor.
    """

    def __init__(self, structure_formats: Union[str, List[str]] = None):
        """
        Constructor

        :param structure_formats: Optional string or list of strings telling us to look for
                    specific formats within the text to separate out/extract
                    in a common way so that clients do not have to reinvent this wheel over
                    and over again.

                    Valid values are:
                        "json" - look for JSON in the message content as structure to report.

                    By default this is None, implying that such parsing is bypassed.
        """
        # Only deal with non-empy lists of strings internally
        self.structure_formats: List[str] = structure_formats
        if self.structure_formats is not None:
            if isinstance(self.structure_formats, str):
                self.structure_formats = [self.structure_formats]
        else:
            self.structure_formats = []

        if not isinstance(self.structure_formats, List):
            raise ValueError(f"Value '{structure_formats}' must be a string, a list of strings, or None")

    def process_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType):
        """
        Process the message.
        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        """
        text: str = chat_message_dict.get("text")
        structure: Dict[str, Any] = chat_message_dict.get("structure")

        if structure is not None:
            # We already have a structure. Do not modify.
            return

        if text is None or len(text) == 0:
            # There is no text to extract anything from
            return

        # Parse structure from the first available format in the answer content
        structure_parser = FirstAvailableStructureParser(self.structure_formats)
        use_structure: Dict[str, Any] = structure_parser.parse_structure(text)
        if use_structure is None:
            return

        # Modify the existing chat_message_dict to reflect extracted structure
        use_text: str = structure_parser.get_remainder()
        chat_message_dict["text"] = use_text
        chat_message_dict["structure"] = structure
