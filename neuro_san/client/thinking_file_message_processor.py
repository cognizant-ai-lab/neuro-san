
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

import json
import uuid

from pathlib import Path
from time import localtime
from time import strftime
from time import time

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor
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

        # Dictionary for storing origins that differ from what might be expected
        self.origins: Dict[str, str] = {}

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
        else:
            # AgentFramework messages carry the final answer, but don't have an origin.
            # Have them get their origin for reporting here (only!) from the chat history.
            extractor = DictionaryExtractor(chat_message_dict)
            histories: List[Dict[str, Any]] = extractor.get("chat_context.chat_histories")
            if histories is not None and len(histories) > 0:
                origin = histories[0].get("origin")
                test_origin_str = Origination.get_full_name_from_origin(origin)
                if test_origin_str is not None:
                    origin_str = test_origin_str

        self.write_message(chat_message_dict, origin_str)

    def write_message(self, response: Dict[str, Any], origin_str: str):
        """
        Writes a line of text attributable to the origin, however we are doing that.
        :param response: The message to write
        :param origin_str: The string representing the origin of the message
        """

        timestamp: float = time()
        response_type: str = response.get("type")
        message_type: ChatMessageType = ChatMessageType.from_response_type(response_type)
        message_type_str: str = ChatMessageType.to_string(message_type)

        text: str = response.get("text")
        structure: Dict[str, Any] = response.get("structure")
        chat_context: Dict[str, Any] = response.get("chat_context")

        if text is None:
            text = ""

        if structure is not None:
            # There is no real text, but there is a structure. JSON-ify it.
            if len(text) > 0:
                text += "\n"
            text += f"```json\n{json.dumps(structure, indent=4, sort_keys=True)}\n```"

        if chat_context is not None:
            # There is no real text, but there is a chat_context. JSON-ify it.
            if len(text) > 0:
                text += "\n"
            text += f"\nchat_context:\n{json.dumps(chat_context, indent=4, sort_keys=True)}\n"

        # Figure out how we are going to report the origin given the message.
        use_origin: str = self._determine_origin_reporting(response, origin_str)

        # Determine the filename to use given the origin_str.
        # Previously we might have used a uuid as a filename, but by default
        # we want the filenames to match the full origin_str.
        origin_filename: str = self.origins.get(origin_str, origin_str)

        try:
            self._write_to_file(origin_filename, origin_str, message_type_str, use_origin, text, timestamp)
        except OSError as os_error:
            # For very deep networks we can sometimes get a "File name too long",
            # which is Error code 63.
            if os_error.errno == 63:

                # Retry with a uuid as file name.
                # If this fails, there's no helping ya.
                origin_filename = str(uuid.uuid4())
                self._write_to_file(origin_filename, origin_str, message_type_str, use_origin, text, timestamp)

                # Squirell that uuid away so results continue to go to the same
                # file over and over again.
                self.origins[origin_str] = origin_filename
            else:
                raise os_error

    def _write_to_file(self, origin_filename: str, origin_str: str,
                       message_type_str: str, use_origin: str, text: str,
                       timestamp: float):

        filename: Path = self.thinking_file
        if self.thinking_dir:
            if origin_filename is None or len(origin_filename) == 0:
                return
            # In case origin_filename is a structured agent name, convert it with "__"
            origin_filename = origin_filename.replace("/", "__")
            filename = Path(self.thinking_dir, origin_filename)

        how_to_open_file: str = "a"
        if not filename.exists():
            how_to_open_file = "w"

        with filename.open(mode=how_to_open_file, encoding="utf-8") as thinking:
            if how_to_open_file == "w":
                # New file, preface it with an origin log.
                thinking.write(f"Agent: {origin_str}\n")

            # Write the message out
            timestamp_str: str = strftime("%Y-%m-%d %H:%M:%S", localtime(timestamp))
            thinking.write(f"\n[{message_type_str}{use_origin}] @ {timestamp_str}:\n")
            thinking.write(text)
            thinking.write("\n")

    def _determine_origin_reporting(self, response: Dict[str, Any], origin_str: str) -> str:

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

        return use_origin
