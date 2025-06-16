
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

import json

from pathlib import Path

from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.internals.messages.origination import Origination
from neuro_san.message_processing.message_processor import MessageProcessor


# pylint: disable=too-many-arguments,too-many-positional-arguments
class ThinkingFileMessageProcessor(MessageProcessor):
    """
    Processes AgentCli input by using the neuro-san streaming API.
    """

    def __init__(self, thinking_file: str, thinking_dir: str):
        """
        Constructor

        :param thinking_file: A string representing the path to a single file where
                              all agent output is combined.  We no longer recommmend this
                              now that we have ...
        :param thinking_dir: A string representing the path to a single directory where
                             each agent in the network gets its own history file according
                             to its agent network origin name.  This is much easier to
                             debug as you do not have to tease apart output from interacting agents.
        """
        self.thinking_file: Path = None
        if thinking_file is not None:
            self.thinking_file = Path(thinking_file)

        self.thinking_dir: Path = None
        if thinking_dir is not None:
            self.thinking_dir = Path(thinking_dir)

    def process_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType):
        """
        Process the message.
        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        """

        # Process any text in the message
        text: str = chat_message_dict.get("text")
        structure: Dict[str, Any] = chat_message_dict.get("structure")
        if text is None and structure is None:
            return

        origin: List[str] = chat_message_dict.get("origin")
        test_origin_str: str = Origination.get_full_name_from_origin(origin)

        origin_str: str = ""
        if test_origin_str is not None:
            origin_str = test_origin_str

        self.write_message(chat_message_dict, origin_str)

    def write_message(self, response: Dict[str, Any], origin_str: str):
        """
        Writes a line of text attributable to the origin, however we are doing that.
        :param response: The message to write
        :param origin_str: The string representing the origin of the message
        """

        response_type: str = response.get("type")
        message_type: ChatMessageType = ChatMessageType.from_response_type(response_type)
        message_type_str: str = ChatMessageType.to_string(message_type)

        text: str = response.get("text")
        structure: Dict[str, Any] = response.get("structure")

        if structure is not None:
            # There is no real text, but there is a structure. JSON-ify it.
            text = json.dumps(structure, indent=4, sort_keys=True)

        filename: Path = self.thinking_file
        if self.thinking_dir:
            if origin_str is None or len(origin_str) == 0:
                return
            filename = Path(self.thinking_dir, origin_str)

        how_to_open_file: str = "a"
        if not filename.exists():
            how_to_open_file = "w"

        with filename.open(mode=how_to_open_file, encoding="utf-8") as thinking:
            use_origin: str = ""

            # Maybe add some context to where message is coming from if not using thinking_dir
            if not self.thinking_dir:
                use_origin += f" from {origin_str}"

            # Maybe add some context as to where the tool result came from if we have info for that.
            tool_result_origin: List[Dict[str, Any]] = response.get("tool_result_origin")
            if tool_result_origin is not None:
                last_origin_only: List[Dict[str, Any]] = [tool_result_origin[-1]]
                origin_str = Origination.get_full_name_from_origin(last_origin_only)
                use_origin += f" (result from {origin_str})"

            # Write the message out
            thinking.write(f"\n[{message_type_str}{use_origin}]:\n")
            thinking.write(text)
            thinking.write("\n")
