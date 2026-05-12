
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
"""
See class comment for details
"""
from typing import Any
from typing import Dict

from neuro_san.service.utils.request_util import RequestUtil
from neuro_san.session.mcp_service_agent_session import MCP_VERSION


class McpRequestUtil:
    """
    Utility class for generating MCP protocol requests and responses.
    """

    @classmethod
    def get_mcp_version(cls) -> str:
        """
        Get the MCP protocol version supported by this service.
        :return: MCP protocol version string.
        """
        return MCP_VERSION

    @classmethod
    def get_handshake_response(cls, request_id) -> Dict[str, Any]:
        """
        Generate a standard MCP handshake response.
        :param request_id: MCP request id;
        :return: json dictionary with handshake request in MCP format suitable for sending to a client.
        """
        return {
            "jsonrpc": "2.0",
            "id": RequestUtil.safe_request_id(request_id),
            "result": {
                "protocolVersion": MCP_VERSION,
                "capabilities": {
                    "logging": {},
                    "prompts": {},
                    "resources": {},
                    "tools": {
                        "listChanged": False
                    }
                },
                "serverInfo": {
                    "name": "Neuro-san-MCPServer",
                    "title": "Neuro-san MCP Server",
                    "version": "1.0.0"
                },
                "instructions": ""
            }
        }
