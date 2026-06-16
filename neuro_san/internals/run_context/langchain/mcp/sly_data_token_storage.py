
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

from logging import Logger
from logging import getLogger
from typing import Any
from typing import Dict
from typing import Optional
from typing import override

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken
from pydantic import ValidationError


class SlyDataTokenStorage(TokenStorage):
    """
    Sly data-based token storage that also stores client credentials info.
    """

    def __init__(self, client_info: Dict[str, Any], tokens: Dict[str, Any]):
        """ Constructor """
        self.logger: Logger = getLogger(self.__class__.__name__)

        self.client_info: Dict[str, Any] = client_info
        self.tokens: Dict[str, Any] = tokens

    @override
    async def get_tokens(self) -> Optional[OAuthToken]:
        """Load OAuth tokens from sly data."""
        if not self.tokens:
            return None

        try:
            return OAuthToken(**self.tokens)

        except (ValidationError, TypeError, ValueError) as errors:
            self.logger.warning("Failed to load token from sly data: %s", errors)
            return None

    async def get_tokens_dict(self) -> Dict[str, Any]:
        """Get raw token dictionary."""
        return self.tokens

    @override
    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Save OAuth tokens to a dictionary in sly data."""
        try:
            # Clear and update token in-place
            self.tokens.clear()
            self.tokens.update(tokens.model_dump(mode="json"))
            self.logger.info("Tokens saved (expires in %s s)", tokens.expires_in)
        except (AttributeError, TypeError) as errors:
            self.logger.error("Failed to save tokens in sly data: %s", errors)

    @override
    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        """
        Load client information from sly data.

        Note:
        - `OAuthClientInformationFull` requires `redirect_uris` to be provided as a list of
        valid URIs.
        - This method is intended for use with **dynamic client registration**, where
        client metadata (e.g., client ID, client secret, redirect URIs) is loaded
        at runtime rather than being hardcoded.
        """
        if not self.client_info:
            return None

        try:
            return OAuthClientInformationFull(**self.client_info)
        except ValidationError as validation_error:
            self.logger.warning("Failed to instantiate OAuthClientInformationFull: %s", validation_error)
            return None

    async def get_client_info_dict(self) -> Dict[str, Any]:
        """Get raw client info dictionary."""
        return self.client_info

    @override
    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Save client information to sly data."""
        try:
            # Clear and update client info in-place
            self.client_info.clear()
            self.client_info.update(client_info.model_dump(mode="json"))
            self.logger.info("Client registered with ID: %s", client_info.client_id)
        except (AttributeError, TypeError) as errors:
            self.logger.error("Failed to save client info in sly data: %s", errors)
