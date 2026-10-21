
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

MCP_SESSION_ID: str = "Mcp-Session-Id"
MCP_PROTOCOL_VERSION: str = "MCP-Protocol-Version"


class ClientSessionPolicy:
    """
    Interface for client sessions handling policy in the MCP service.
    """

    def create_session(self) -> ClientSession:
        """
        Create a new client session with the unique client id.
        This method may return None if session creation is not supported
        by the policy.

        :return: The created ClientSession or None
        """
        raise NotImplementedError

    def activate_session(self, session_id: str) -> bool:
        """
        Activate an existing client session with the given session id.
        Note that multiple session activations are currently allowed
        :param session_id: The session id to activate.
                 May be None if sessions are not supported by the policy
        :return: True if successful;
                 False if session with given id does not exist
        """
        raise NotImplementedError

    def delete_session(self, session_id: str) -> bool:
        """
        Delete an existing client session with the given session id.
        :param session_id: The session id to delete
                 May be None if sessions are not supported by the policy
        :return: True if successful;
                 False if session with given id does not exist
        """
        raise NotImplementedError

    def is_session_active(self, session_id: str) -> bool:
        """
        Check if the session with the given id is active.
        :param session_id: The session id to check
                 May be None if sessions are not supported by the policy
        :return: True if session exists and is active;
                 False otherwise
        """
        raise NotImplementedError
