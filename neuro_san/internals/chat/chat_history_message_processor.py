
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
from numbers import Number
from typing import Any
from typing import Dict
from typing import List

from copy import copy

from neuro_san.message.processors.message_processor import MessageProcessor
from neuro_san.message.types.chat_message_type import ChatMessageType


class ChatHistoryMessageProcessor(MessageProcessor):
    """
    MessageProcessor implementation for processing a single message
    in a chat history.
    """

    def __init__(self, max_message_history: int = None):
        """
        Constructor

        :param max_message_history: The maximum number of messages to preserve
                in the message history, not including the instructions.
                The default value of None implies there is no maximum.
                Non-positive numbers revert to no-maximum behavior.
        """
        self.max_message_history: int = max_message_history
        if self.max_message_history is not None:
            if not isinstance(self.max_message_history, Number):
                # If we don't have a number we don't have a max.
                self.max_message_history = None
            else:
                # Be sure we are dealing with an integer
                self.max_message_history = int(self.max_message_history)

        self.message_history: List[Dict[str, Any]] = []
        self.saw_first_system: bool = False

    def get_message_history(self) -> List[Dict[str, Any]]:
        """
        :return: The filtered message history
        """
        return self.message_history

    def process_messages(self, chat_message_dicts: List[Dict[str, Any]]):
        """
        Convenience method for processing lists of messages.
        :param chat_message_dicts: The messages to process.
        """
        super().process_messages(chat_message_dicts)

        # See if we need to curtail chat history at all.
        if self.max_message_history is None or self.max_message_history <= 1:
            # Nothing to do.
            return

        # Save the first item in the list. This is the redacted placeholder for instructions
        instructions: Dict[str, Any] = self.message_history.pop(0)

        # Preserve the most recent n elements in the message history
        self.message_history = self.message_history[-self.max_message_history:]

        # Prepend the instructions to the list
        self.message_history.insert(0, instructions)

    def process_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType):
        """
        Process the message.
        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        """
        if message_type not in (ChatMessageType.HUMAN, ChatMessageType.SYSTEM, ChatMessageType.AI):
            # Don't send any messages over the wire that won't be re-ingestable.
            return

        transformed_message_dict: Dict[str, Any] = chat_message_dict
        if not self.saw_first_system and message_type == ChatMessageType.SYSTEM:
            # Redact the first SYSTEM message we see. This has the front-man prompt in it,
            # and when read in, we replace it with what the agent has anyway to prevent
            # a prompting takeover.
            transformed_message_dict = self.redact_instructions(chat_message_dict)
            self.saw_first_system = True
        else:
            # Transform the message with properly escaped text.
            transformed_message_dict = self.escape_message(chat_message_dict)

        if transformed_message_dict is not None:
            self.message_history.append(transformed_message_dict)

    def redact_instructions(self, chat_message_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Redacts the text instructions of the given system message.
        These will get replaced by the agent's instructions anyway to preserve
        server-side intent.
        """
        redacted: Dict[str, Any] = copy(chat_message_dict)
        redacted["text"] = "<redacted>"
        return redacted

    def escape_message(self, chat_message_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare a message such that it can be re-ingested by the system nicely.
        This means properly escaping any text that is sent.
        """
        transformed: Dict[str, Any] = copy(chat_message_dict)
        text: str = transformed.get("text")

        if text is None:
            return None

        # Braces are a problem for chat history being read back into the system
        # if they are not properly escaped.

        # First replace any pre-escaped braces with normal braces
        text_1 = text.replace("{{", "{")
        text_2 = text_1.replace("}}", "}")

        # Now replace normal braces with escaped braces.
        # Idea is to catch everything pre-escaped or not
        text_3 = text_2.replace("{", "{{")
        use_text = text_3.replace("}", "}}")

        # JSON spec does not allow control characters in strings and newlines in particular
        # can be a problem for http clients that expect one full JSON message per line.
        # Replace any lurking newlines with the 2 raw characters \ and n.
        # DEF - for the future.

        transformed["text"] = use_text
        return transformed
