
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

import json
from typing import Any
from typing import Dict
from typing import Tuple

from http import HTTPStatus

from neuro_san.internals.interfaces.dictionary_validator import DictionaryValidator
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler
from neuro_san.service.utils.mcp_server_context import McpServerContext
from neuro_san.service.mcp.interfaces.client_session_policy import ClientSessionPolicy
from neuro_san.service.mcp.interfaces.client_session_policy import MCP_SESSION_ID, MCP_PROTOCOL_VERSION
from neuro_san.service.mcp.util.mcp_errors_util import McpErrorsUtil
from neuro_san.service.mcp.validation.tool_request_validator import ToolRequestValidator
from neuro_san.service.mcp.mcp_errors import McpError
from neuro_san.service.mcp.processors.mcp_tools_processor import McpToolsProcessor
from neuro_san.service.mcp.processors.mcp_resources_processor import McpResourcesProcessor
from neuro_san.service.mcp.processors.mcp_prompts_processor import McpPromptsProcessor
from neuro_san.service.mcp.processors.mcp_initialize_processor import McpInitializeProcessor
from neuro_san.service.mcp.processors.mcp_ping_processor import McpPingProcessor


class McpRootHandler(BaseRequestHandler):
    """
    Class implementing top-level MCP request handler.
    Note that since /mcp is our single MCP endpoint,
    all MCP requests are handled by this class.
    """
    # pylint: disable=attribute-defined-outside-init
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def initialize(self, **kwargs):
        """
        This method is called by Tornado framework to allow
        injecting service-specific data into local handler context.
        """
        # Initialize members of the base class BaseRequestHandler:
        super().initialize(**kwargs)

        # type: McpServerContext
        self.mcp_context: McpServerContext = self.server_context.get_mcp_server_context()
        # A dictionary of string (describing scope) to
        #     AgentNetworkStorage instance which keeps all the AgentNetwork instances
        #     of a particular grouping.
        self.network_storage_dict: Dict[str, AgentNetworkStorage] = self.server_context.get_network_storage_dict()

        # For tool requests, we need to validate tool call arguments:
        self.tool_request_validator: ToolRequestValidator = ToolRequestValidator(self.openapi_service_spec)

        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        headers: str = "Content-Type, Transfer-Encoding"
        metadata_headers: str = ", ".join(self.forwarded_request_metadata)
        if len(metadata_headers) > 0:
            headers += f", {metadata_headers}"
        # Set all allowed headers:
        self.set_header("Access-Control-Allow-Headers", headers)

    async def post(self):
        """
        Implementation of the top-level POST request handler for MCP call.
        """
        # pylint: disable=too-many-locals
        # pylint: disable=too-many-branches
        # pylint: disable=too-many-statements

        metadata: Dict[str, Any] = self.get_metadata()
        request_id = "unknown"

        try:
            # Parse JSON body
            data = json.loads(self.request.body)

            # Validate incoming request content:
            request_validator: DictionaryValidator = self.mcp_context.get_request_validator()
            validation_errors = request_validator.validate(data)
            if validation_errors:
                extra_error: str = "; ".join(validation_errors)
                error_msg: Dict[str, Any] =\
                    McpErrorsUtil.get_protocol_error(request_id, McpError.InvalidRequest, extra_error)
                self.set_status(HTTPStatus.BAD_REQUEST)
                self.write(error_msg)
                self.logger.error(self.get_metadata(), f"Error: Invalid MCP request: {extra_error}")
                self.do_finish()
                return
        except json.JSONDecodeError as exc:
            error_msg: Dict[str, Any] =\
                McpErrorsUtil.get_protocol_error(
                    request_id,
                    McpError.ParseError,
                    "Invalid JSON format")
            self.set_status(HTTPStatus.BAD_REQUEST)
            self.write(error_msg)
            self.logger.error(self.get_metadata(), "error: Invalid JSON format: %s", str(exc))
            self.do_finish()
            return

        # We have valid MCP request:
        request_id = data.get("id", "absent")
        method: str = data.get("method")
        session_id: str = self.request.headers.get(MCP_SESSION_ID, None)
        protocol_version: str = self.request.headers.get(MCP_PROTOCOL_VERSION, None)
        if protocol_version:
            protocol_version = protocol_version.strip()

        # First check if we have handshake/initialize session requests -
        # these do not require valid protocol version or valid session:
        # MCP connection/session lifecycle is defined here:
        # https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
        new_session_id, request_done = await self.handle_handshake(method, data, session_id, request_id, metadata)
        if request_done:
            if new_session_id:
                self.set_header(MCP_SESSION_ID, new_session_id)
            self.do_finish()
            return

        # For all other methods, we need to have valid protocol version and valid session id,
        # it is possible that session id is not provided at all, i.e. None
        if protocol_version != self.mcp_context.get_protocol_version():
            extra_error: str = f"unsupported protocol version {protocol_version}"
            error_msg: Dict[str, Any] =\
                McpErrorsUtil.get_protocol_error(request_id, McpError.InvalidProtocolVersion, extra_error)
            self.set_status(HTTPStatus.BAD_REQUEST)
            self.write(error_msg)
            self.logger.error(self.get_metadata(), f"error: {extra_error}")
            self.do_finish()
            return
        session_policy: ClientSessionPolicy = self.mcp_context.get_session_policy()
        session_active = session_policy.is_session_active(session_id)
        if not session_active:
            extra_error: str = "invalid or inactive session id"
            error_msg: Dict[str, Any] =\
                McpErrorsUtil.get_protocol_error(request_id, McpError.InvalidSession, extra_error)
            self.set_status(HTTPStatus.UNAUTHORIZED)
            self.write(error_msg)
            self.logger.error(self.get_metadata(), f"error: {extra_error}")
            self.do_finish()
            return

        try:
            if method == "tools/list":
                tools_processor: McpToolsProcessor =\
                    McpToolsProcessor(
                        self.logger,
                        self.network_storage_dict,
                        self.agent_policy,
                        self.tool_request_validator)
                result_dict: Dict[str, Any] = await tools_processor.list_tools(request_id, metadata)
                self.set_status(HTTPStatus.OK)
                self.write(result_dict)
            elif method == "tools/call":
                tools_processor: McpToolsProcessor =\
                    McpToolsProcessor(
                        self.logger,
                        self.network_storage_dict,
                        self.agent_policy,
                        self.tool_request_validator)
                call_params: Dict[str, Any] = data.get("params", {})
                tool_name: str = call_params.get("name")
                call_args: Dict[str, Any] = call_params.get("arguments", {})
                # Validate tool arguments:
                validation_errors = self.tool_request_validator.validate(call_args)
                if validation_errors:
                    extra_error: str = "; ".join(validation_errors)
                    error_msg: Dict[str, Any] = \
                        McpErrorsUtil.get_protocol_error(request_id, McpError.InvalidRequest)
                    self.set_status(HTTPStatus.BAD_REQUEST)
                    self.write(error_msg)
                    self.logger.error(self.get_metadata(), f"Error: Invalid tool call request: {extra_error}")
                    return

                prompt: Dict[str, Any] = call_args.get("user_message", {})
                chat_context: Dict[str, Any] = call_args.get("chat_context", None)
                chat_filter: Dict[str, Any] = call_args.get("chat_filter", None)
                sly_data: Dict[str, Any] = call_args.get("sly_data", None)
                result_dict: Dict[str, Any] =\
                    await tools_processor.call_tool(
                        request_id, metadata,
                        tool_name,
                        prompt,
                        chat_context,
                        chat_filter,
                        sly_data)
                self.set_status(HTTPStatus.OK)
                self.write(result_dict)
            elif method == "resources/list":
                resources_processor: McpResourcesProcessor = McpResourcesProcessor(self.logger)
                result_dict: Dict[str, Any] = await resources_processor.list_resources(request_id, metadata)
                self.set_status(HTTPStatus.OK)
                self.write(result_dict)
            elif method == "prompts/list":
                prompts_processor: McpPromptsProcessor = McpPromptsProcessor(self.logger)
                result_dict: Dict[str, Any] = await prompts_processor.list_prompts(request_id, metadata)
                self.set_status(HTTPStatus.OK)
                self.write(result_dict)
            else:
                # Method is not found/not supported
                extra_error: str = f"method {method} not found"
                error_msg: Dict[str, Any] =\
                    McpErrorsUtil.get_protocol_error(request_id, McpError.NoMethod, extra_error)
                self.set_status(HTTPStatus.BAD_REQUEST)
                self.write(error_msg)
                self.logger.error(self.get_metadata(), f"error: Method {method} not found")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            error_msg: Dict[str, Any] =\
                McpErrorsUtil.get_protocol_error(
                    request_id,
                    McpError.ServerError,
                    f"exception during {method} handling")
            self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.write(error_msg)
            self.logger.error(self.get_metadata(), "error: Server error %s: %s", method, str(exc))
        finally:
            # We are done with response stream:
            self.do_finish()

    async def handle_handshake(
            self,
            method: str,
            request_data: Dict[str, Any],
            session_id: str,
            request_id,
            metadata: Dict[str, Any]) -> Tuple[str, bool]:
        """
        Handle handshake/initialize session request if request method is applicable.
        :param method: MCP method name
        :param request_data: MCP request data dictionary
        :param session_id: MCP client session id taken from request headers
        :request_id: MCP request id
        :param metadata: http-level request metadata;
        :return: tuple of 2 values:
                 first - new session id if it was generated here;
                         None otherwise
                second - True if request was handled here;
                         False otherwise
        """
        try:
            if method == "initialize":
                # Handle handshake/initialize session request
                handshake_processor: McpInitializeProcessor = McpInitializeProcessor(self.mcp_context, self.logger)
                result_dict, session_id =\
                    await handshake_processor.initialize_handshake(request_id, metadata, request_data["params"])
                if session_id is not None:
                    self.set_header(MCP_SESSION_ID, session_id)
                self.set_status(HTTPStatus.OK)
                self.write(result_dict)
                return session_id, True
            if method == "notifications/initialized":
                # Handle client acknowledgement of initialization response,
                # this activates the session on the server side for further operations.
                handshake_processor: McpInitializeProcessor = McpInitializeProcessor(self.mcp_context, self.logger)
                result: bool = await handshake_processor.activate_session(session_id, metadata)
                response_code: int = HTTPStatus.ACCEPTED if result else HTTPStatus.NOT_FOUND
                if session_id is not None:
                    self.set_header(MCP_SESSION_ID, session_id)
                self.set_status(response_code)
                # We do not have any response body for this request
                return None, True
            if method == "ping":
                # Handle client-side ping,
                # we don't care about sessions here.
                ping_processor: McpPingProcessor = McpPingProcessor(self.logger)
                _ = await ping_processor.ping(session_id, metadata)
                response_code: int = HTTPStatus.OK
                self.set_status(response_code)
                # We do not have any response body for this request
                return None, True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            error_msg: Dict[str, Any] = \
                McpErrorsUtil.get_protocol_error(
                    request_id,
                    McpError.ServerError,
                    f"exception during {method} handling")
            self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.write(error_msg)
            self.logger.error(self.get_metadata(), "error: Server error %s: %s", method, str(exc))
            return None, True
        return None, False

    async def delete(self):
        """
        Implementation of top-level DELETE request handler for MCP call.
        """

        metadata: Dict[str, Any] = self.get_metadata()
        request_id = "unknown"

        # We only expect MCP client session id taken from request headers:
        session_id: str = self.request.headers.get(MCP_SESSION_ID, None)

        request_status: int = HTTPStatus.NO_CONTENT
        if session_id is not None:
            session_policy: ClientSessionPolicy = self.mcp_context.get_session_policy()
            deleted: bool = session_policy.delete_session(session_id)
            if deleted:
                self.logger.info(metadata, "Session %s deleted by client", session_id)
            else:
                extra_error: str = "Session id not found"
                error_msg: Dict[str, Any] =\
                    McpErrorsUtil.get_protocol_error(request_id, McpError.InvalidSession, extra_error)
                self.set_status(HTTPStatus.NOT_FOUND)
                self.write(error_msg)
                self.logger.error(metadata, f"Error: {extra_error}")
        else:
            # No session id is provided in this request:
            # report bad request
            request_status = HTTPStatus.UNAUTHORIZED
        self.set_status(request_status)
        self.do_finish()

    async def get(self):
        """
        Implementation of top-level GET request handler for MCP call.
        """
        # Consider GET request for MCP endpoint to be a service health check
        self.set_status(HTTPStatus.OK)
        self.do_finish()
