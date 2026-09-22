
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

from requests import post
from requests import Response

from leaf_common.time.timeout import Timeout

from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.session.abstract_http_service_agent_session import AbstractHttpServiceAgentSession
from neuro_san.session.mcp_chat_response_dictionary_converter import McpChatResponseDictionaryConverter

# MCP protocol version supported by this MCP session
# Protocol specification is available at:
# https://modelcontextprotocol.io/specification/2025-06-18
MCP_VERSION: str = "2025-06-18"


class McpServiceAgentSession(AbstractHttpServiceAgentSession, AgentSession):
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

        # The name the server advertises for this network, learned by function()
        # from tools/list. Servers may advertise a nested network under a
        # provider-safe spelling ("deep/math_guy" becomes "deep__math_guy") or a
        # custom manifest "mcp_name" ("calculator"), while users keep passing the
        # network name (e.g. --agent deep/math_guy). Until function() has looked,
        # tools/call uses the network name, which every neuro-san server accepts:
        # older servers key on it directly and newer ones pass an unadvertised
        # name through to the same network-keyed lookup.
        self.advertised_tool_name: str = None

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
        response: Response = None
        response_dict: Dict[str, Any] = None
        try:
            response = post(path, json=handshake_dict, headers=headers, timeout=self.timeout_in_seconds)
            response.raise_for_status()
            response_dict = json.loads(response.text)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

        # Extract the protocol version from the handshake response
        empty_dict: Dict[str, Any] = {}
        result_dict: Dict[str, Any] = response_dict.get("result", empty_dict)
        self.protocol_version: str = result_dict.get("protocolVersion", None)

        # Confirm the protocol version is supported by this client
        if self.protocol_version not in [MCP_VERSION]:
            raise ValueError(f"Unsupported MCP protocol version: {self.protocol_version}")

        # Acknowledge the successful handshake
        ack_dict: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        try:
            response = post(path, json=ack_dict, headers=headers, timeout=self.timeout_in_seconds)
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
        _ = request_dict
        # Get the list of tools available from the service
        use_request_dict: Dict[str, Any] = {
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
        response: Response = None
        response_dict: Dict[str, Any] = None
        try:
            response = post(path, json=use_request_dict, headers=headers, timeout=self.timeout_in_seconds)
            response.raise_for_status()
            response_dict = json.loads(response.text)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

        empty_dict: Dict[str, Any] = {}
        empty_list: List[Dict[str, Any]] = []
        result_dict: Dict[str, Any] = response_dict.get("result", empty_dict)
        tools_list: List[Dict[str, Any]] = result_dict.get("tools", empty_list)
        use_tool: Dict[str, Any] = self.find_tool_for_network(tools_list)
        if use_tool is None:
            # Nothing stands for the network any more, so forget whatever an
            # earlier listing advertised; tools/call then falls back to the
            # network name rather than a stale one.
            self.advertised_tool_name = None
            return None

        # Remember the name this server uses so tools/call sends a name the
        # server can resolve. Under a custom "mcp_name" this is a name we could
        # not have derived from the network name.
        self.advertised_tool_name = use_tool.get("name", None)
        tool_description: str = use_tool.get("description", None)
        if tool_description is None:
            return None

        return {
            "function": {"description": tool_description}
        }

    def find_tool_for_network(self, tools_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Picks the tools/list entry that stands for the network this session was
        created for.

        A server that renames a tool, whether to the provider-safe spelling
        ("deep__math_guy") or to a custom manifest "mcp_name" ("calculator"),
        keeps the network name in the entry's MCP "title". So when an entry has
        a title, the title says which network it stands for; an entry without
        one stands for the network only if its "name" is the network name, as
        servers from before the rename advertise it. The client never guesses
        from the spelling: an unrelated network can legitimately be named
        "deep__math_guy", and an entry named "math_guy" but titled "x/y" is
        x/y's tool, not math_guy's.

        :param tools_list: The "tools" list of a tools/list result
        :return: The first entry that stands for the network, or None if there is none
        """
        for tool in tools_list:
            use_tool: Dict[str, Any] = tool
            name: str = use_tool.get("name", None)
            if name is None:
                # Not a callable tool entry: tools/call needs a name.
                continue
            # An empty title carries no information, so it falls back to the name.
            network_name: str = use_tool.get("title", None) or name
            if network_name == self.agent_name:
                return use_tool
        return None

    def connectivity(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the ConnectivityRequest.
        :return: A dictionary version of the ConnectivityResponse.
        """
        # Not used in MCP protocol; return empty connectivity info
        response: Dict[str, Any] = {}
        return response

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
        # Call the tool by the name function() saw the server advertise. A caller
        # that skips function() (e.g. SimpleOneShot) has not learned it, so it
        # sends the network name instead, which every neuro-san server accepts.
        tool_name: str = self.advertised_tool_name
        if tool_name is None:
            tool_name = self.agent_name

        # Pack the chat request dictionary into an MCP method call format:
        mcp_payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": request_dict,
            },
        }

        headers: Dict[str, str] = self.get_headers()
        headers["Content-Type"] = "application/json"
        headers[self.MCP_PROTOCOL_VERSION] = self.protocol_version

        path: str = self.get_request_path("streaming_chat")
        try:
            with post(path, json=mcp_payload, headers=headers,
                      stream=True, timeout=self.streaming_timeout_in_seconds) as response:
                response.raise_for_status()

                for line in response.iter_lines(decode_unicode=True):
                    if line.strip():  # Skip empty lines
                        # Each line is a JSON object representing an MCP tool call(chat) response
                        result_dict: Dict[str, Any] = json.loads(line)
                        result_dict = McpChatResponseDictionaryConverter().to_dict(result_dict)
                        yield result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    def close(self):
        """
        No-op: this MCP session cannot cancel an in-flight tool call.

        The MCP transport here is request/response, not streaming: requests.post()
        does not return until the server sends response headers, and the neuro-san
        MCP handler writes the response only after awaiting the full tool run (see
        mcp_root_handler.py). There is therefore no abortable in-flight connection
        to release mid-run -- closing anything client-side cannot terminate the
        server-side work -- so this session deliberately does NOT claim to support
        cancellation. Provided as a documented no-op so callers can treat all
        session types uniformly.
        """
        return

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
