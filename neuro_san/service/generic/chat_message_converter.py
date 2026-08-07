
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
from enum import Enum

from leaf_common.serialization.interface.dictionary_converter import DictionaryConverter

from neuro_san.messages.types.chat_message_type import ChatMessageType


class ChatMessageConverter(DictionaryConverter):
    """
    Helper class to prepare chat response messages
    for external clients consumption.
    """
    def to_dict(self, obj: object) -> Dict[str, object]:
        """
        :param obj: The object (chat response) to be converted into a dictionary
        :return: chat response dictionary in format expected by clients
        """
        # Do "the safe" copy, moving over only json serializable values.
        # Note that values of ChatMessageType are passed through,
        # because they are handled by a separate post-processing step.
        response_dict = self.to_json_safe(obj)
        # This is where ChatMessageType enum values are converted:
        self.convert(response_dict)
        return response_dict

    def convert(self, response_dict: Dict[str, Any]):
        """
        Convert chat response message to a format expected by external clients:
        :param response_dict: chat response message to be sent out
        """
        # Ensure that we return ChatMessageType as a string in output json
        message_dict: Dict[str, Any] = response_dict.get('response', None)
        if message_dict is not None:
            self.convert_message(message_dict)

    def convert_message(self, message_dict: Dict[str, Any]):
        """
        Convert chat message to a format expected by external clients:
        :param message_dict: chat message to process
        """
        # Ensure that we return ChatMessageType as a string in output json
        response_type = message_dict.get('type', None)
        if response_type is not None:
            message_dict['type'] =\
                ChatMessageType.from_response_type(response_type).name
        chat_context: Dict[str, Any] = message_dict.get('chat_context', None)
        if chat_context is not None:
            for chat_history in chat_context.get("chat_histories", []):
                for chat_message in chat_history.get("messages", []):
                    self.convert_message(chat_message)

    def from_dict(self, obj_dict: Dict[str, object]) -> object:
        """
        :param obj_dict: The data-only dictionary to be converted into an object
        :return: An object instance created from the given dictionary.
                If obj_dict is None, the returned object should also be None.
                If obj_dict is not the correct type, it is also reasonable
                to return None.
        """
        raise NotImplementedError

    JSON_PRIMITIVES = (str, int, float, bool, type(None))
    SKIP_TYPES = (ChatMessageType,)

    def to_json_safe(self, obj: Any):
        """
        Recursively convert obj into a JSON-serializable structure.
        Don't touch the values of SKIP_TYPES.
        Non-serializable values are replaced with None.
        """
        # Fast path: JSON primitives or types we need to skip:
        if isinstance(obj, (self.SKIP_TYPES, self.JSON_PRIMITIVES)):
            return obj

        # Enums → their value (or None if value is not primitive)
        if isinstance(obj, Enum):
            if isinstance(obj.value, self.JSON_PRIMITIVES):
                return obj.value
            return None

        # Dict → keys must be strings, values recursively processed
        if isinstance(obj, dict):
            safe_dict = {}
            for k, v in obj.items():
                if isinstance(k, str):
                    safe_dict[k] = self.to_json_safe(v)
                # Non-string keys are dropped
            return safe_dict

        # List / tuple → list
        if isinstance(obj, (list, tuple)):
            return [self.to_json_safe(v) for v in obj]

        # Everything else → None
        return None
