
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

import json
from json import JSONDecodeError
from logging import Logger
from logging import getLogger
import os
from pathlib import Path
from pathlib import PosixPath
from typing import Any
from typing import Dict
from typing import Optional
from urllib.parse import urlparse
from urllib.parse import ParseResult

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken
from pydantic import ValidationError


class FileTokenStorage(TokenStorage):
    """
    File-based token storage that also stores client credentials info.
    """

    def __init__(self, mcp_server_url: str):
        """ Constructor """
        self.logger: Logger = getLogger(self.__class__.__name__)

        # Determine base path for storing tokens and client info
        base_path: Optional[str] = os.getenv("AGENT_MCP_AUTH_DIR")
        # If not set, use default paths based on OS
        if not base_path:
            if os.name == "nt":
                base_path = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "mcp-auth")
            else:
                base_path = os.path.join(os.path.expanduser("~"), ".mcp-auth")

        # Create directory for the specific MCP server using its hostname
        parsed: ParseResult = urlparse(mcp_server_url)
        if not parsed.hostname:
            raise ValueError(f"Invalid MCP server URL: {mcp_server_url}")
        mcp_server_host: str = parsed.hostname
        self.mcp_info_path: PosixPath = Path(base_path).expanduser() / mcp_server_host
        self.mcp_info_path.mkdir(parents=True, exist_ok=True)
        self.tokens_file: PosixPath = self.mcp_info_path / "tokens.json"
        self.client_info_file: PosixPath = self.mcp_info_path / "client_info.json"

    async def get_tokens(self) -> Optional[OAuthToken]:
        """Load OAuth tokens from file."""
        if not self.tokens_file.exists():
            return None

        try:
            with open(self.tokens_file, "r", encoding="utf-8") as token_file:
                data = json.load(token_file)
                return OAuthToken(**data)
        except JSONDecodeError as json_error:
            self.logger.warning("Failed to parse tokens file: %s", json_error)
            return None
        except OSError as os_error:
            self.logger.warning("Failed to read tokens file: %s", os_error)
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Save OAuth tokens to file."""
        try:
            with open(self.tokens_file, "w", encoding="utf-8") as token_file:
                json.dump(tokens.model_dump(mode="json"), token_file, indent=2)
            self.logger.info("Tokens saved (expires in %d s)", tokens.expires_in)
        except OSError as os_error:
            self.logger.error("Failed to write tokens file: %s", os_error)

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        """
        Load client information from file.

        Note:
        - `OAuthClientInformationFull` requires `redirect_uris` to be provided as a list of
        valid URIs.
        - This method is intended for use with **dynamic client registration**, where
        client metadata (e.g., client ID, client secret, redirect URIs) is loaded
        at runtime rather than being hardcoded.
        """
        if not self.client_info_file.exists():
            return None

        try:
            data = await self.get_client_credentials() or {}
            return OAuthClientInformationFull(**data)
        except ValidationError as validation_error:
            self.logger.warning("Failed to instantiate OAuthClientInformationFull: %s", validation_error)
            return None

    async def get_client_credentials(self) -> Dict[str, Any]:
        """
        Load client credentails from file. Similar to get_client_info() but return dictionary instead of
        OAuthClientInformationFull so it can be used for grant type that does not required `redirect_uris`
        """
        if not self.client_info_file.exists():
            return None

        try:
            with open(self.client_info_file, "r", encoding="utf-8") as client_file:
                return json.load(client_file)
        except JSONDecodeError as json_error:
            self.logger.warning("Failed to parse client info file: %s", json_error)
            return None
        except OSError as os_error:
            self.logger.warning("Failed to read client info file: %s", os_error)
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Save client information to file."""
        try:
            with open(self.client_info_file, "w", encoding="utf-8") as client_file:
                json.dump(client_info.model_dump(mode="json"), client_file, indent=2)
            self.logger.info("Client registered with ID: %s", client_info.client_id)
        except OSError as os_error:
            self.logger.error("Failed to write client info file: %s", os_error)

    async def delete_storage(self) -> None:
        """
        Delete stored if it is empty. This is used to clean up storage if no credentials are stored,
        which can happen if the server requires no authentication.
        """
        try:
            self.mcp_info_path.rmdir()
            self.logger.info(
                "No client info found. Authentication may not need to be performed. "
                "Deleted empty storage directory: %s", self.mcp_info_path
            )
        except OSError as os_error:
            self.logger.error("Failed to delete storage files: %s", os_error)
