
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

from neuro_san.service.mcp.interfaces.client_session_policy import ClientSessionPolicy
from neuro_san.service.mcp.interfaces.client_session import ClientSession


class McpNoSessionsPolicy(ClientSessionPolicy):
    """
    Policy class for scenario when client sessions are not supported by the MCP service.
    """

    def create_session(self) -> ClientSession:
        """
        Create a None client session if client sessions are not supported.
        :return: None
        """
        return None

    def activate_session(self, session_id: str) -> bool:
        """
        For "no sessions" policy, always return True.
        """
        return True

    def delete_session(self, session_id: str) -> bool:
        """
        For "no sessions" policy, always return True.
        """
        return True

    def is_session_active(self, session_id: str) -> bool:
        """
        For "no sessions" policy, always return True.
        """
        return True
