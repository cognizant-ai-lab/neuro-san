
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
from typing import Generator

import json
import requests

from leaf_common.time.timeout import Timeout

from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.interfaces.concierge_session import ConciergeSession
from neuro_san.session.abstract_http_service_agent_session import AbstractHttpServiceAgentSession
from neuro_san.session.mcp_chat_response_dictionary_converter import McpChatResponseDictionaryConverter

# MCP protocol version supported by this MCP session
# Protocol specification is available at:
# https://modelcontextprotocol.io/specification/2025-06-18
MCP_VERSION: str = "2025-06-18"


class McpServiceAgentSession(AbstractHttpServiceAgentSession, AgentSession, ConciergeSession):
    """
    Implementation of AgentSession that talks to an MCP protocol service.
    This is largely only used by command-line tests.
    """
    MCP_PROTOCOL_VERSION: str = "MCP-Protocol-Version"

    # pylint: disable=too-many-arguments,too-many-positional-arguments, too-many-locals
    def __init__(self, host: str = None,
                 port: str = None,
                 timeout_in_seconds: int = 30,
                 metadata: Dict[str, str] = None,
                 security_cfg: Dict[str, Any] = None,
                 umbrella_timeout: Timeout = None,
                 streaming_timeout_in_seconds: int = None,
                 agent_name: str = None,
                 session_name: str = "Neuro SAN MCP Session"):
        """
        Creates an MCP protocol session.

        :param host: the service host to connect to
                        If None, will use a default
        :param port: the service port
                        If None, will use a default
        :param timeout_in_seconds: timeout to use when communicating
                        with the service
        :param metadata: A grpc metadata of key/value pairs to be inserted into
                         the header. Default is None. Preferred format is a
                         dictionary of string keys to string values.
        :param security_cfg: An optional dictionary of parameters used to
                        secure the TLS and the authentication of the gRPC
                        connection.  Supplying this implies use of a secure
                        GRPC Channel.  Default is None, uses insecure channel.
        :param umbrella_timeout: A Timeout object under which the length of all
                        looping and retries should be considered
        :param streaming_timeout_in_seconds: timeout to use when streaming to/from
                        the service. Default is None, indicating connection should
                        stay open until the (last) result is yielded.
        :param agent_name: The name of the agent to talk to
        :param session_name: The name of the session used in handshake exchange.
        """
        super().__init__(host=host, port=port, timeout_in_seconds=timeout_in_seconds,
                         metadata=metadata, security_cfg=security_cfg, umbrella_timeout=umbrella_timeout,
                         streaming_timeout_in_seconds=streaming_timeout_in_seconds, agent_name=agent_name)
        # Do initial handshake and protocol negotiation
        handshake_dict: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_VERSION,
                "capabilities": {
                    "roots": {
                        "listChanged": False
                    },
                    "sampling": {},
                    "elicitation": {}
                },
                "clientInfo": {
                    "name": session_name,
                    "title": session_name,
                    "version": "1.0.0"
                }
            }
        }
        headers: Dict[str, str] = self.get_headers()
        headers["Content-Type"] = "application/json"

        path: str = self.get_request_path("initialize")
        try:
            response = requests.post(path, json=handshake_dict, headers=headers, timeout=self.timeout_in_seconds)
            response.raise_for_status()
            response_dict = json.loads(response.text)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

        # Extract the protocol version from the handshake response
        self.protocol_version: str = response_dict.get("result", {}).get("protocolVersion", None)

        # Confirm the protocol version is supported by this client
        if self.protocol_version not in [MCP_VERSION]:
            raise ValueError(f"Unsupported MCP protocol version: {self.protocol_version}")

        # Acknowledge the successful handshake
        ack_dict: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        try:
            response = requests.post(path, json=ack_dict, headers=headers, timeout=self.timeout_in_seconds)
            response.raise_for_status()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    def function(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the FunctionRequest
                    protobufs structure. Has the following keys:
                        <None>
        :return: A dictionary version of the FunctionResponse
                    protobufs structure. Has the following keys:
                "function" - the dictionary description of the function
        """
        # Get the list of tools available from the service
        request_dict: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {
            }
        }
        headers: Dict[str, str] = self.get_headers()
        headers["Content-Type"] = "application/json"
        headers[self.MCP_PROTOCOL_VERSION] = self.protocol_version

        path: str = self.get_request_path("tools/list")
        try:
            response = requests.post(path, json=request_dict, headers=headers, timeout=self.timeout_in_seconds)
            response.raise_for_status()
            response_dict = json.loads(response.text)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

        tools_list: List[Dict[str, Any]] = response_dict.get("result", {}).get("tools", [])
        for tool in tools_list:
            name: str = tool.get("name", None)
            if name == self.agent_name:
                tool_description: str = tool.get("description", None)
                if tool_description is not None:
                    return {
                        "function": {"description": tool_description}
                    }

        return None

    def connectivity(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the ConnectivityRequest.
        :return: A dictionary version of the ConnectivityResponse.
        """
        # Not used in MCP protocol; return empty connectivity info
        request_dict: Dict[str, Any] = {}
        return request_dict

    def streaming_chat(self, request_dict: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
        """
        :param request_dict: A dictionary version of the ChatRequest
                    protobufs structure. Has the following keys:
            "user_message" - A ChatMessage dict representing the user input to the chat stream
            "chat_context" - A ChatContext dict representing the state of the previous conversation
                            (if any)
        :return: An iterator of dictionary versions of the ChatResponse
                    protobufs structure. Has the following keys:
            "response" - An optional ChatMessage dictionary.  See chat.proto for details.

            Note that responses to the chat input might be numerous and will come as they
            are produced until the system decides there are no more messages to be sent.
        """
        # Pack the chat request dictionary into an MCP method call format:
        mcp_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": self.agent_name,
                "arguments": request_dict,
            },
        }

        headers: Dict[str, str] = self.get_headers()
        headers["Content-Type"] = "application/json"
        headers[self.MCP_PROTOCOL_VERSION] = self.protocol_version

        path: str = self.get_request_path("streaming_chat")
        try:
            with requests.post(path, json=mcp_payload, headers=headers,
                               timeout=self.streaming_timeout_in_seconds) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if line.strip():  # Skip empty lines
                        # Each line is a JSON object representing an MCP tool call(chat) response
                        result_dict = json.loads(line)
                        result_dict = McpChatResponseDictionaryConverter().to_dict(result_dict)
                        yield result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    def list(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A request dictionary. Not used for this implementation.
        :return: A dictionary version of the MCP protocol "tools/list" response.
                "tools" - the sequence of dictionaries describing available MCP tools
        """
        # Get the list of tools available from the service
        mcp_payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {
            }
        }
        headers: Dict[str, str] = self.get_headers()
        headers["Content-Type"] = "application/json"
        headers[self.MCP_PROTOCOL_VERSION] = self.protocol_version

        path: str = self.get_request_path("list")
        try:
            with requests.post(path, json=mcp_payload, headers=headers,
                               timeout=self.streaming_timeout_in_seconds) as response:
                response.raise_for_status()
                result_dict = response.json()
                #result_dict = McpChatResponseDictionaryConverter().to_dict(result_dict)
                return result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    def get_request_path(self, method: str) -> str:
        """
        :param method: The method endpoint we wish to reach
        :return: The full URL for accessing the method, given the host, port and agent_name.
        """
        _ = method
        scheme: str = "http"
        if self.security_cfg is not None:
            scheme = "https"
        return f"{scheme}://{self.use_host}:{self.use_port}/mcp"
