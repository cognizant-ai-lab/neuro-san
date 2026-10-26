
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

from neuro_san.service.mcp.interfaces.client_session import ClientSession


class McpClientSession(ClientSession):
    """
    Class representing a client session with the MCP service.
    """

    def __init__(self, session_id: str):
        self.session_id: str = session_id

        # Flag indicating if the session is properly initialized
        # by handshake sequence and now active.
        self.session_is_active: bool = False

    def get_id(self) -> str:
        """
        Get the session id.
        """
        return self.session_id

    def is_active(self) -> bool:
        """
        Check if the session is active.
        """
        return self.session_is_active

    def set_active(self, is_active: bool) -> None:
        """
        Set the session active flag.
        """
        self.session_is_active = is_active
