
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

import asyncio
import json

from aiohttp import ClientPayloadError
from aiohttp import ClientOSError
from aiohttp import ClientSession
from aiohttp import ClientTimeout

from neuro_san.interfaces.async_agent_session import AsyncAgentSession
from neuro_san.session.abstract_http_service_agent_session import AbstractHttpServiceAgentSession


class AsyncHttpServiceAgentSession(AbstractHttpServiceAgentSession, AsyncAgentSession):
    """
    Implementation of AsyncAgentSession that talks to an HTTP service.
    """

    async def function(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the FunctionRequest
                    protobufs structure. Has the following keys:
                        <None>
        :return: A dictionary version of the FunctionResponse
                    protobufs structure. Has the following keys:
                "function" - the dictionary description of the function
        """
        path: str = self.get_request_path("function")
        result_dict: Dict[str, Any] = None
        try:
            timeout: ClientTimeout = None
            if self.timeout_in_seconds is not None:
                timeout = ClientTimeout(self.timeout_in_seconds)

            async with ClientSession(headers=self.get_headers(),
                                     timeout=timeout
                                     ) as session:
                async with session.get(path, json=request_dict) as response:
                    result_dict = await response.json()
                    return result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    async def connectivity(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
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
        result_dict: Dict[str, Any] = None
        try:
            timeout: ClientTimeout = None
            if self.timeout_in_seconds is not None:
                timeout = ClientTimeout(self.timeout_in_seconds)
            async with ClientSession(headers=self.get_headers(),
                                     timeout=timeout
                                     ) as session:
                async with session.get(path, json=request_dict) as response:
                    result_dict = await response.json()
                    return result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    async def streaming_chat(self, request_dict: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
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
            # To specify complete timeout value, we must use "total" parameter of ClientTimeout.
            # See https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientTimeout for details.
            timeout: ClientTimeout = ClientTimeout(total=None)
            # That will make sure that the connection will stay open until the (last) result is yielded,
            # which is what we want here.
            # Not specifying "total" parameter will invoke lower-level aiohttp timeout, which is 300 seconds by default
            if self.streaming_timeout_in_seconds is not None:
                timeout = ClientTimeout(total=self.streaming_timeout_in_seconds)
            async with ClientSession(headers=self.get_headers(),
                                     timeout=timeout
                                     ) as session:
                async with session.post(path, json=request_dict) as response:
                    # Check for successful response status
                    response.raise_for_status()

                    # Iterate over the content stream as it comes in.
                    # Note: We used to iterate over lines with the simpler:
                    #           async for line in response.content:
                    #               ... blah blah ...
                    #       but that could fail with ValueError("Chunk too big")
                    #       if a single line was too long.
                    accumulator: bytearray = bytearray(b"")
                    async for data in response.content.iter_chunked(max_chunk_size):

                        # Concatenate data as it comes in
                        accumulator.extend(data)

                        # Try to find our line separator
                        index: int = accumulator.find(separator)
                        while index >= 0:

                            # Grab a single line
                            unicode_line: str = accumulator[:index].decode("utf-8").strip()
                            if unicode_line:    # Skip empty lines
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

        except (asyncio.TimeoutError, ClientOSError, ClientPayloadError) as exc:
            # Pass on a couple of asserts that are known to represent
            # real problems that a client has to deal with.
            # We figure this is OK for streaming_chat() because normally
            # in order to get to using streaming_chat() clients will most
            # often call function() first, and that will have the blanket
            # helpful asserts for the newly initiated.
            raise exc

        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Assume the newly initiated need some more help.
            raise ValueError(self.help_message(path)) from exc
