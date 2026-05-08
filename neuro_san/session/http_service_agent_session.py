
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
from typing import Generator

import json
import requests

from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.session.abstract_http_service_agent_session import AbstractHttpServiceAgentSession


class HttpServiceAgentSession(AbstractHttpServiceAgentSession, AgentSession):
    """
    Implementation of AgentSession that talks to an HTTP service.
    This is largely only used by command-line tests.
    """

    def function(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the FunctionRequest
                    protobufs structure. Has the following keys:
                        <None>
        :return: A dictionary version of the FunctionResponse
                    protobufs structure. Has the following keys:
                "function" - the dictionary description of the function
        """
        path: str = self.get_request_path("function")
        try:
            response = requests.get(path, json=request_dict, headers=self.get_headers(),
                                    timeout=self.timeout_in_seconds)
            result_dict = json.loads(response.text)
            return result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    def connectivity(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the ConnectivityRequest
                    protobufs structure. Has the following keys:
                        <None>
        :return: A dictionary version of the ConnectivityResponse
                    protobufs structure. Has the following keys:
                "connectivity_info" - the list of connectivity descriptions for
                                    each node in the agent network the service
                                    wants the client ot know about.
        """
        path: str = self.get_request_path("connectivity")
        try:
            response = requests.get(path, json=request_dict, headers=self.get_headers(),
                                    timeout=self.timeout_in_seconds)
            result_dict = json.loads(response.text)
            return result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    def streaming_chat(self, request_dict: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
        """
        :param request_dict: A dictionary version of the ChatRequest
                    protobufs structure. Has the following keys:
            "user_message" - A ChatMessage dict representing the user input to the chat stream
            "chat_context" - A ChatContext dict representing the state of the previous conversation
                            (if any)
        :return: An iterator of dictionary versions of the ChatResponse
                    protobufs structure. Has the following keys:
            "response"      - An optional ChatMessage dictionary.  See chat.proto for details.

            Note that responses to the chat input might be numerous and will come as they
            are produced until the system decides there are no more messages to be sent.
        """
        separator: bytes = b"\n"
        max_chunk_size: int = 64 * 1024
        path: str = self.get_request_path("streaming_chat")
        try:
            with requests.post(path, json=request_dict, headers=self.get_headers(),
                               stream=True,
                               timeout=self.streaming_timeout_in_seconds) as response:
                response.raise_for_status()

                # Iterate over the content stream as it comes in.
                # Note: We used to iterate over lines with the simpler:
                #           for line in response.iter_lines(decode_unicode=True):
                #               ...
                #       but that delegated UTF-8 handling to the response's
                #       Content-Type charset (which the server may not set),
                #       and split on universal newlines instead of strict "\n".
                #       We now buffer raw bytes, split strictly on "\n",
                #       and decode UTF-8 explicitly -- mirroring the async client.
                accumulator: bytearray = bytearray(b"")
                for data in response.iter_content(chunk_size=max_chunk_size):

                    # Concatenate data as it comes in
                    accumulator.extend(data)

                    # Try to find our line separator
                    index: int = accumulator.find(separator)
                    while index >= 0:

                        # Grab a single line
                        unicode_line: str = accumulator[:index].decode("utf-8").strip()
                        if unicode_line:  # Skip empty lines
                            # We have a line with something in it.
                            # Decode and yield as a dictionary
                            result_dict = json.loads(unicode_line)
                            yield result_dict

                        # Remove the previous line from the accumulator
                        del accumulator[:index + len(separator)]

                        # Allow for case of multiple lines in one chunk
                        index = accumulator.find(separator)

                # If there is anything left in the accumulator, yield it
                if len(accumulator) > 0:
                    unicode_line: str = accumulator.decode("utf-8").strip()
                    if unicode_line:
                        result_dict = json.loads(unicode_line)
                        yield result_dict

        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc
