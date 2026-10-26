
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
from typing import Tuple

from neuro_san.service.http.logging.http_logger import HttpLogger
from neuro_san.service.utils.mcp_server_context import McpServerContext
from neuro_san.service.mcp.interfaces.client_session import ClientSession
from neuro_san.service.mcp.util.mcp_request_util import McpRequestUtil


class McpInitializeProcessor:
    """
    Class implementing client session initialization.
    """
    def __init__(self, mcp_context: McpServerContext, logger: HttpLogger):
        self.logger: HttpLogger = logger
        self.mcp_context: McpServerContext = mcp_context

    async def initialize_handshake(
            self,
            request_id,
            metadata: Dict[str, Any],
            params: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """
        Process initial protocol handshake.
        :param request_id: MCP request id;
        :param metadata: http-level request metadata;
        :param params: dictionary with handshake parameters;
        :return: json dictionary with handshake response
        """
        # Currently, we do not use any parameters from the client
        # for protocol version or capabilities negotiation.
        # We simply return the server capabilities.
        # Also: we don't look at possible session ID present in the incoming request.
        # Future versions may implement more complex negotiation logic.

        _ = params
        # Create new client session:
        session: ClientSession = self.mcp_context.get_session_policy().create_session()
        session_id: str = None
        if session:
            session_id = session.get_id()
            self.logger.info(metadata, "Created new MCP client session with id: %s", session_id)

        response_dict: Dict[str, Any] = McpRequestUtil.get_handshake_response(request_id)
        return response_dict, session_id

    async def activate_session(
            self,
            session_id: str,
            metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Activate existing client session.
        :param session_id: session id to activate;
        :
        :param metadata: http-level request metadata;
        :return: True if successful;
                 False if session with given id does not exist
        """
        success: bool = self.mcp_context.get_session_policy().activate_session(session_id)
        if not session_id:
            session_id = "N/A"
        if success:
            self.logger.info(metadata,
                             "Activated MCP client session with id: %s",
                             session_id)
        else:
            self.logger.info(metadata,
                             "Failed to activate MCP client session with id: %s - session not found",
                             session_id)
        return success
