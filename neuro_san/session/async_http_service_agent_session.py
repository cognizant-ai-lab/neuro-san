
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
from typing import Generator

import json

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
        path: str = self.get_request_path("streaming_chat")
        try:
            timeout: ClientTimeout = None
            if self.streaming_timeout_in_seconds is not None:
                timeout = ClientTimeout(self.streaming_timeout_in_seconds)
            async with ClientSession(headers=self.get_headers(),
                                     timeout=timeout
                                     ) as session:
                async with session.post(path, json=request_dict) as response:
                    # Check for successful response status
                    response.raise_for_status()

                    # Iterate over the content stream line by line
                    async for line in response.content:
                        unicode_line = line.decode('utf-8')
                        if unicode_line.strip():    # Skip empty lines
                            result_dict = json.loads(unicode_line)
                            yield result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc
