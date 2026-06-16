
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
from typing import Literal
from typing import Optional
from typing import override
import httpx

from mcp.client.auth import OAuthClientProvider
from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthClientMetadata


class ClientCredentialsOauthProvider(OAuthClientProvider):
    """OAuth provider for client_credentials grant with client_id + client_secret.

    This provider sets client_info directly, bypassing dynamic client registration.
    Use this when you already have client credentials (client_id and client_secret) and there is no refresh token.

    The authentication flow proceeds as follows:
    1. When an HTTP request is sent to an MCP server, the async_auth_flow method is triggered.
    2. The provider attempts to load client information and tokens from storage. This logic is implemented in
    the _initialize() method, which is overridden to set client_info directly to prevent invalid parameters.
    3. If the server responds with 401 Unauthorized, the provider attempts metadata discovery, including:
        - Protected Resource Metadata
        - OAuth Authorization Server Metadata
    4. Attempt to get tokens from the token endpoint in _perform_authorization() method.
    Use the endpoint from discovery if available, otherwise use the token_endpoint parameter.
    5. If the server responds with 403 Forbidden, the provider attempts to update the scopes from
    the protected resource metadata.
    7. Retry the authentication flow with the new scopes or tokens.

    This is taken from the MCP SDK:
    https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/client/auth/extensions/client_credentials.py

    However, the SDK's ClientCredentialsOauthProvider has two limitations:
    - No user-provided endpoint support - Only uses endpoints from metadata discovery,
    doesn't allow manual configuration
    - Bug in client_secret_post method - The token exchange fails when using this authentication method

    Thus, we modify the code from the MCP SDK to add support for user-provided token endpoint and
    fix the client_secret_post method.

    WARNING: This class overrides private methods from the SDK's OAuth implementation.

    FRAGILITY NOTICE:
    - We override _initialize() and _perform_authorization()
    - These are PRIVATE methods that may change without notice
    - Any SDK update could break this implementation

    FUTURE WORK:
    - The following GitHub issue/PR tracks making this properly extensible in the SDK
        - https://github.com/modelcontextprotocol/python-sdk/issues/2121
        - https://github.com/modelcontextprotocol/python-sdk/issues/2128
        - https://github.com/modelcontextprotocol/python-sdk/pull/2140
    - If/when that lands, we should migrate to use official extension points
    - If not accepted, we should build our own OAuth client
    """

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        client_id: str,
        client_secret: Optional[str],
        token_endpoint: str = None,
        token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post", None] = "client_secret_basic",
        scopes: str | None = None,
        timeout: float = 300.0
    ) -> None:
        """Constructor"""
        # Build minimal client_metadata for the base class
        client_metadata = OAuthClientMetadata(
            redirect_uris=None,
            grant_types=["client_credentials"],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scopes,
        )
        # There is no need for redirect or callback.
        super().__init__(server_url, client_metadata, storage, None, None, timeout)
        # Store client_info to be set during _initialize - no dynamic registration needed
        # Note that client info is obtained through dynamic client registration in the MCP SDK,
        # but since we are bypassing dynamic registration, we need to set client_info directly.
        self._fixed_client_info = OAuthClientInformationFull(
            redirect_uris=None,
            client_id=client_id,
            client_secret=client_secret,
            grant_types=["client_credentials"],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scopes,
        )
        self.token_endpoint: str = token_endpoint

    @override
    async def _initialize(self) -> None:
        """Load stored tokens and set pre-configured client_info."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        # Client info can also be loaded from the storage here,
        # but we set it directly to prevent invalid or missing needed parameters.
        self.context.client_info = self._fixed_client_info
        self._initialized = True

    @override
    async def _perform_authorization(self) -> httpx.Request:
        """
        Perform client_credentials authorization.

        Note that this method originally performs user authorization and exchange code for token.
        Thus, we override it to perform client credentials flow instead of user authorization and token exchange.
        """
        return await self._exchange_token_client_credentials()

    async def _exchange_token_client_credentials(self) -> httpx.Request:
        """
        Build token exchange request for client_credentials grant.

        A helper method to build the token request for client credentials flow, which is used in _perform_authorization.
        """
        token_data: Dict[str, Any] = {
            "grant_type": "client_credentials",
            "client_id": self.context.client_info.client_id,
        }

        headers: Dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}

        # Use standard auth methods (client_secret_basic, client_secret_post, none)
        token_data, headers = self.context.prepare_token_auth(token_data, headers)

        if self.context.should_include_resource_param(self.context.protocol_version):
            token_data["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:
            token_data["scope"] = self.context.client_metadata.scope

        # Determine token endpoint URL: use provided token_endpoint if available, otherwise use endpoint from discovery
        token_url: str = self.token_endpoint or self._get_token_endpoint()
        return httpx.Request("POST", token_url, data=token_data, headers=headers)
