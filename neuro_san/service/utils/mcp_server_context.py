
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

from leaf_common.serialization.util.text_file_reader import TextFileReader

from neuro_san import TOP_LEVEL_DIR
from neuro_san.internals.interfaces.dictionary_validator import DictionaryValidator
from neuro_san.service.mcp.validation.mcp_request_validator import McpRequestValidator
from neuro_san.service.mcp.interfaces.client_session_policy import ClientSessionPolicy
from neuro_san.service.mcp.session.mcp_no_sessions_policy import McpNoSessionsPolicy
from neuro_san.service.mcp.util.mcp_request_util import McpRequestUtil


class McpServerContext:
    """
    Class representing the server run-time context,
    necessary for handling MCP clients requests.
    """

    def __init__(self):
        self.protocol_schema_filepath = None
        self.protocol_schema = None
        self.session_policy = None
        self.request_validator = None
        self.enabled: bool = False

    def set_enabled(self, enabled: bool) -> None:
        """
        Enable or disable the MCP service.
        :param enabled: Flag indicating if the service should be enabled
        """
        if not self.enabled and enabled:
            print(">>>>>>>>>>>> Enabling MCP service...")
            # MCP service is being enabled, set it up:
            schema_name: str = f"service/mcp/validation/mcp-schema-{McpRequestUtil.get_mcp_version()}.json"
            self.protocol_schema_filepath = TOP_LEVEL_DIR.get_file_in_basis(schema_name)
            try:
                schema_str: str = TextFileReader.read_text_file(self.protocol_schema_filepath)
                self.protocol_schema = json.loads(schema_str)
                self.request_validator = McpRequestValidator(self.protocol_schema)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise RuntimeError(f"Cannot load MCP protocol schema from "
                                   f"'{self.protocol_schema_filepath}': {str(exc)}") from exc
            # Create a new session manager:
            self.session_policy = McpNoSessionsPolicy()
        self.enabled = enabled

    def is_enabled(self) -> bool:
        """
        Check if the MCP service is enabled.
        :return: True if the service is enabled, False otherwise
        """
        return self.enabled

    def get_protocol_version(self) -> str:
        """
        Get the MCP protocol version supported by this service.
        :return: The MCP protocol version
        """
        return McpRequestUtil.get_mcp_version()

    def get_request_validator(self) -> DictionaryValidator:
        """
        Get the request validator for this context.
        :return: The request validator
        """
        return self.request_validator

    def get_session_policy(self) -> ClientSessionPolicy:
        """
        Get the MCP session policy for this context.
        :return: The session policy instance
        """
        return self.session_policy
