
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

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata

from neuro_san.internals.run_context.langchain.mcp.client_credentials_oauth_provider import \
    ClientCredentialsOauthProvider
from neuro_san.internals.run_context.langchain.mcp.extended_oauth_provider import ExtendedOauthClientProvider
from neuro_san.internals.run_context.langchain.mcp.file_token_storage import FileTokenStorage
from neuro_san.internals.run_context.langchain.mcp.oauth_callback_handler import OauthCallbackHandler
from neuro_san.internals.run_context.langchain.mcp.authorization_code_oauth_provider import \
    AuthorizationCodeOauthProvider


# pylint: disable=too-many-instance-attributes
class OauthProviderFactory:
    """
    Factory for creating OAuth providers based on stored credentials and configuration.
    Supports multiple authentication flows: client_credentials, authorization_code with
    pre-registration, and client id metadata documents or dynamic client registration.
    """
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        server_url: str,
        storage: FileTokenStorage,
        auth_endpoint: Optional[str] = None,
        token_endpoint: Optional[str] = None,
        client_metadata: Optional[OAuthClientMetadata] = None,
        callback_port: int = 3000,
        timeout: float = 300.0
    ):
        """
        Initialize OAuth provider factory.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.server_url = server_url
        self.storage = storage
        self.auth_endpoint = auth_endpoint
        self.token_endpoint = token_endpoint
        self.client_metadata = client_metadata
        self.callback_port = callback_port
        self.timeout = timeout
        self.callback_handler: Optional[OauthCallbackHandler] = None

    async def get_auth(self) -> OAuthClientProvider:
        """
        Get appropriate OAuth provider based on stored credentials.

        Flow priority:
        1. Client credentials flow (if client_id + client_secret with client_credentials grant)
        2. Authorization code with pre-registration (if client_id + client_secret exists)
        3. Authorization code with client id metadata documents or dynamic registration (fallback)
        """
        credentials: Dict[str, Any] = await self.storage.get_client_credentials()

        # Flow 1: Client Credentials
        if self._can_use_client_credentials(credentials):
            return self._create_client_credentials_provider(credentials)

        # Flow 2: Authorization Code with Pre-registration
        if self._has_client_credentials(credentials):
            return await self._create_preregistered_auth_code_provider(credentials)

        # Flow 3: Authorization Code with Dynamic Registration
        return await self._create_dynamic_auth_code_provider()

    def _can_use_client_credentials(self, credentials: Optional[Dict[str, Any]]) -> bool:
        """Check if client credentials flow is available."""
        return (
            credentials is not None
            and credentials.get("client_id") is not None
            and credentials.get("client_secret") is not None
            and "client_credentials" in (credentials.get("grant_types") or [])
        )

    def _has_client_credentials(self, credentials: Optional[Dict[str, Any]]) -> bool:
        """Check if we have client credentials (but not client_credentials grant)."""
        return (
            credentials is not None
            and credentials.get("client_id") is not None
            and credentials.get("client_secret") is not None
        )

    def _create_client_credentials_provider(
            self,
            credentials: Dict[str, Any]
    ) -> ClientCredentialsOauthProvider:
        """Create client credentials OAuth provider."""
        self.logger.info("✓ Using client_credentials flow")

        return ClientCredentialsOauthProvider(
            server_url=self.server_url,
            storage=self.storage,
            client_id=credentials.get("client_id"),
            client_secret=credentials.get("client_secret"),
            token_endpoint=self.token_endpoint,
            token_endpoint_auth_method=credentials.get("token_endpoint_auth_method") or "client_secret_basic",
            scopes=credentials.get("scope")
        )

    async def _create_preregistered_auth_code_provider(
            self,
            credentials: Dict[str, Any]
    ) -> AuthorizationCodeOauthProvider:
        """Create authorization code provider with pre-registered client."""
        self.logger.info("✓ Using authorization_code flow with pre-registered client")

        if self.auth_endpoint and self.token_endpoint:
            self.logger.info("The following endpoints are provided:")
            self.logger.info("Authorization endpoint: %s", self.auth_endpoint)
            self.logger.info("Token endpoint: %s", self.token_endpoint)

        # Start callback server
        await self._ensure_callback_handler()

        return AuthorizationCodeOauthProvider(
            server_url=self.server_url,
            storage=self.storage,
            client_id=credentials.get("client_id"),
            client_secret=credentials.get("client_secret"),
            authorization_endpoint=self.auth_endpoint,
            token_endpoint=self.token_endpoint,
            token_endpoint_auth_method=credentials.get("token_endpoint_auth_method") or "client_secret_basic",
            redirect_handler=self.callback_handler.handle_redirect,
            callback_handler=self.callback_handler.wait_for_callback
        )

    async def _create_dynamic_auth_code_provider(self) -> ExtendedOauthClientProvider:
        """Create authorization code provider with dynamic client registration."""
        self.logger.info("✓ Using authorization_code flow with dynamic client registration")

        # Start callback server
        await self._ensure_callback_handler()

        # Ensure client metadata exists
        client_metadata = self._get_or_create_client_metadata()

        return ExtendedOauthClientProvider(
            server_url=self.server_url,
            client_metadata=client_metadata,
            storage=self.storage,
            redirect_handler=self.callback_handler.handle_redirect,
            callback_handler=self.callback_handler.wait_for_callback,
            timeout=self.timeout
        )

    async def _ensure_callback_handler(self) -> None:
        """Ensure callback handler is created and server is started."""
        if not self.callback_handler:
            self.callback_handler = OauthCallbackHandler(port=self.callback_port)
            await self.callback_handler.start_server()

    def _get_or_create_client_metadata(self) -> OAuthClientMetadata:
        """Get existing client metadata or create default."""
        if self.client_metadata:
            # Ensure redirect_uris is set
            if not self.client_metadata.redirect_uris:
                self.client_metadata.redirect_uris = [
                    f"http://localhost:{self.callback_port}/callback"
                ]
            return self.client_metadata

        # Create default client metadata
        return OAuthClientMetadata(
            redirect_uris=[f"http://localhost:{self.callback_port}/callback"],
            grant_types=["authorization_code"]
        )

    async def cleanup(self) -> None:
        """
        Clean up resources.

        Stops callback server if running and deletes storage if no client credentails were saved
        (indicating the server required no authentication).
        """
        # Stop callback server if it was started
        if self.callback_handler:
            await self.callback_handler.stop_server()
            self.callback_handler = None

        # If no client info is stored, delete storage folder
        # This indicates the server required no authentication
        credentials: Dict[str, Any] = await self.storage.get_client_credentials()
        if credentials is None:
            await self.storage.delete_storage()
            self.logger.debug("Storage deleted (no authentication required)")
