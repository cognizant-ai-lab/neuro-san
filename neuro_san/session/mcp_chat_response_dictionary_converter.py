
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
from typing import Sequence

from leaf_common.serialization.interface.dictionary_converter import DictionaryConverter

from neuro_san.internals.messages.chat_message_type import ChatMessageType


class McpChatResponseDictionaryConverter(DictionaryConverter):
    """
    A DictionaryConverter implementation which can convert MCP service response
    to native neuro-san service response format.
    """

    def to_dict(self, obj: object) -> Dict[str, object]:
        """
        :param obj: The MCP response to be converted into a dictionary
        :return: A data-only dictionary that represents both:
                 native neuro-san service response - under "response" key
                 original MCP response - under "mcp_response" key
        """
        empty: Dict[str, Any] = {}
        if not isinstance(obj, dict):
            return empty
        chat_response: Dict[str, Any] = obj
        result: Dict[str, Any] = chat_response.get("result", None)
        if result is None:
            return empty
        has_error: bool = result.get("isError", True)
        if has_error:
            return empty
        content_seq: Sequence[Dict[str, Any]] = result.get("content", [])
        if len(content_seq) == 0:
            return empty
        # "structuredContent" is MCP standard key for content with additional structure.
        structured_data: Dict[str, Any] = result.get("structuredContent", None)
        response: Dict[str, Any] = content_seq[0]
        final_response: Dict[str, Any] = {
            "response": {
                "type": ChatMessageType.AGENT_FRAMEWORK.name,
                "text": response.get("text", "")
            },
            "mcp_response": chat_response
        }
        if structured_data is not None:
            message_structured_data: Dict[str, Any] = structured_data.get("structure", None)
            if message_structured_data is not None:
                final_response["response"]["structure"] = message_structured_data
            chat_context_data: Dict[str, Any] = structured_data.get("chat_context", None)
            if chat_context_data is not None:
                final_response["response"]["chat_context"] = chat_context_data
        return final_response

    def from_dict(self, obj_dict: Dict[str, object]) -> object:
        """
        :param obj_dict: The data-only dictionary to be converted into an object
        :return: An object instance created from the given dictionary.
                If obj_dict is None, the returned object should also be None.
                If obj_dict is not the correct type, it is also reasonable
                to return None.
        """
        raise NotImplementedError
