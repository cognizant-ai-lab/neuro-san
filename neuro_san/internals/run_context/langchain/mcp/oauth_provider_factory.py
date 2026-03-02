
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

from httpx import Auth
from mcp.client.auth import TokenStorage

from neuro_san.internals.run_context.langchain.mcp.client_credentials_oauth_provider import \
    ClientCredentialsOauthProvider
from neuro_san.internals.run_context.langchain.mcp.refresh_token_oauth_provider import RefreshTokenOauthProvider


# pylint: disable=too-many-instance-attributes
class OauthProviderFactory:
    """
    Factory for creating OAuth providers based on stored credentials and configuration.
    Supports machine-to-machine authentication flows: client credentials and refresh token.
    """
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        token_endpoint: Optional[str] = None,
        timeout: float = 300.0
    ):
        """
        Initialize OAuth provider factory.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.server_url = server_url
        self.storage = storage
        self.token_endpoint = token_endpoint
        self.timeout = timeout

    async def get_auth(self) -> Optional[Auth]:
        """
        Get appropriate OAuth provider based on stored credentials and tokens.

        Flow implementation:
        - Refresh token flow (if refresh token is available)
        - Client credentials flow (no refresh token, but client credentials are available)
        """
        credentials: Dict[str, Any] = await self.storage.get_client_info_dict()
        tokens: Dict[str, Any] = await self.storage.get_tokens_dict()
        refresh_token: str = tokens.get("refresh_token")

        if credentials:
            # If there is a refresh token, prioritize refresh token flow to reuse existing authorization
            if refresh_token:
                return await self._create_refresh_token_provider(credentials)
            return await self._create_client_credentials_provider(credentials)

        # No client credentials, no auth provider can be created
        return None

    async def _create_client_credentials_provider(self, credentials: Dict[str, Any]) -> Auth:
        """Create client credentials OAuth provider."""
        self.logger.info("✓ Using client_credentials flow for %s", self.server_url)

        return ClientCredentialsOauthProvider(
            server_url=self.server_url,
            storage=self.storage,
            client_id=credentials.get("client_id"),
            client_secret=credentials.get("client_secret"),
            token_endpoint=self.token_endpoint,
            token_endpoint_auth_method=credentials.get("token_endpoint_auth_method", "client_secret_basic"),
            scopes=credentials.get("scope"),
            timeout=self.timeout
        )

    async def _create_refresh_token_provider(self, credentials: Dict[str, Any]) -> Auth:
        """Create refresh token provider."""
        self.logger.info("✓ Using refresh token flow for %s", self.server_url)

        return RefreshTokenOauthProvider(
            server_url=self.server_url,
            storage=self.storage,
            client_id=credentials.get("client_id"),
            client_secret=credentials.get("client_secret"),
            token_endpoint=self.token_endpoint,
            token_endpoint_auth_method=credentials.get("token_endpoint_auth_method", "client_secret_basic"),
            scopes=credentials.get("scope"),
            timeout=self.timeout
        )
