
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

        import json
        print(f"~~~~~~~~~~~~~~~~~~~~~~~~~~~ NS => MCP Chat Response: {json.dumps(chat_response, indent=4)}")

        result: Dict[str, Any] = chat_response.get("result", None)
        if result is None:
            return empty
        has_error: bool = result.get("isError", True)
        if has_error:
            return empty
        content_seq: Sequence[Dict[str, Any]] = result.get("content", [])
        if len(content_seq) == 0:
            return empty
        content_dict: Dict[str, Any] = content_seq[0]
        response_dict: Dict[str, Any] = {
            "response": {
                "type": ChatMessageType.AGENT_FRAMEWORK.name,
                "text": content_dict.get("text", "")
            },
            "mcp_response": chat_response
        }
        sly_data_dict: Dict[str, Any] = result.get("sly_data", None)
        if sly_data_dict:
            response_dict["response"]["sly_data"] = sly_data_dict
            # This is a workaround to ensure message will make it through
            # client-side message filters
            response_dict["response"]["chat_context"] = {}
            print(f"~~~~~~~~~~~~~~~~~~~~~~~~~~~ Added sly_data to response: {json.dumps(response_dict, indent=4)}")
        return response_dict

    def from_dict(self, obj_dict: Dict[str, object]) -> object:
        """
        :param obj_dict: The data-only dictionary to be converted into an object
        :return: An object instance created from the given dictionary.
                If obj_dict is None, the returned object should also be None.
                If obj_dict is not the correct type, it is also reasonable
                to return None.
        """
        raise NotImplementedError
