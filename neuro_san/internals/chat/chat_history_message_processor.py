
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
from typing import Optional

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
            if not isinstance(self.max_message_history, (int, float)):
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

        # A history that starts with the redacted placeholder for the instructions
        # keeps it in front of whatever is trimmed. The server's own histories
        # carry no system message and start at the first user message.
        instructions: Optional[Dict[str, Any]] = None
        if len(self.message_history) > 0 and self.message_history[0].get("type") == ChatMessageType.SYSTEM:
            instructions = self.message_history.pop(0)

        # Preserve the most recent n elements in the message history
        self.message_history = self.message_history[-self.max_message_history:]

        # Start at a user message. A cut inside a turn would leave a tool result
        # without the call that asked for it, which providers reject.
        while len(self.message_history) > 0 and self.message_history[0].get("type") != ChatMessageType.HUMAN:
            self.message_history.pop(0)

        if instructions is not None:
            self.message_history.insert(0, instructions)

    def process_message(self, chat_message_dict: Dict[str, Any], message_type: ChatMessageType):
        """
        Process the message.
        :param chat_message_dict: The ChatMessage dictionary to process.
        :param message_type: The ChatMessageType of the chat_message_dictionary to process.
        """
        if message_type not in (ChatMessageType.HUMAN, ChatMessageType.SYSTEM, ChatMessageType.AI) \
                and not self.is_tool_result(chat_message_dict, message_type):
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
            transformed_message_dict = self.keep_message(chat_message_dict)

        if transformed_message_dict is not None:
            self.message_history.append(transformed_message_dict)

    @staticmethod
    def is_tool_result(chat_message_dict: Dict[str, Any], message_type: ChatMessageType) -> bool:
        """
        Tells whether the message answers a tool call made earlier in the history.

        Such a message carries the id of the call it answers, so the next turn can
        put the call and its result back together. A tool result without that id
        is the stand-alone form and stays out of the history.

        :param chat_message_dict: The ChatMessage dictionary to examine
        :param message_type: The ChatMessageType of the dictionary
        :return: True if the message is an AGENT_TOOL_RESULT with a tool_call_id
        """
        if message_type != ChatMessageType.AGENT_TOOL_RESULT:
            return False
        tool_call_id: Any = chat_message_dict.get("tool_call_id")
        return isinstance(tool_call_id, str) and len(tool_call_id) > 0

    def redact_instructions(self, chat_message_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Redacts the text instructions of the given system message.
        These will get replaced by the agent's instructions anyway to preserve
        server-side intent.
        """
        redacted: Dict[str, Any] = copy(chat_message_dict)
        redacted["text"] = "<redacted>"
        return redacted

    @staticmethod
    def keep_message(chat_message_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Copies a message into the history as it is.

        The text is not changed. It goes back to the model as a message, not through
        a template, so braces and other characters need no escaping and the model
        sees the text exactly as it was written.

        :param chat_message_dict: The ChatMessage dictionary to copy
        :return: A shallow copy of the dictionary, or None if the message carries no text at all
        """
        if chat_message_dict.get("text") is None:
            return None
        return copy(chat_message_dict)
