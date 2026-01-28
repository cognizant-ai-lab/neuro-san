
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
from typing import Literal
import httpx

from mcp.shared.auth import OAuthClientMetadata
from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull

from neuro_san.internals.run_context.langchain.mcp.extended_oauth_provider import ExtendedOauthClientProvider


class ExtendedClientCredentialsOauthProvider(ExtendedOauthClientProvider):
    """OAuth provider for client_credentials grant with client_id + client_secret.

    This provider sets client_info directly, bypassing dynamic client registration.
    Use this when you already have client credentials (client_id and client_secret) and grant type is
    client credentials. This is taken directly from the MCP SDK:
    https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/client/auth/extensions/client_credentials.py
    but extends ExtendedOauthClientProvider instead of OAuthClientProvider to handle non-json token responses
    and add token_endpoint as an optional parameter.
    """

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        client_id: str,
        client_secret: str,
        token_endpoint: str = None,
        token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = "client_secret_basic",
        scopes: str | None = None,
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
        super().__init__(server_url, client_metadata, storage, None, None, 300.0)
        # Store client_info to be set during _initialize - no dynamic registration needed
        self._fixed_client_info = OAuthClientInformationFull(
            redirect_uris=None,
            client_id=client_id,
            client_secret=client_secret,
            grant_types=["client_credentials"],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scopes,
        )
        self.token_endpoint: str = token_endpoint

    async def _initialize(self) -> None:
        """Load stored tokens and set pre-configured client_info."""
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = self._fixed_client_info
        self._initialized = True

    async def _perform_authorization(self) -> httpx.Request:
        """Perform client_credentials authorization."""
        return await self._exchange_token_client_credentials()

    async def _exchange_token_client_credentials(self) -> httpx.Request:
        """Build token exchange request for client_credentials grant."""
        token_data: dict[str, Any] = {
            "grant_type": "client_credentials",
        }

        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}

        # Use standard auth methods (client_secret_basic, client_secret_post, none)
        token_data, headers = self.context.prepare_token_auth(token_data, headers)

        if self.context.should_include_resource_param(self.context.protocol_version):
            token_data["resource"] = self.context.get_resource_url()

        if self.context.client_metadata.scope:
            token_data["scope"] = self.context.client_metadata.scope

        token_url = self._get_token_endpoint() or self.token_endpoint
        return httpx.Request("POST", token_url, data=token_data, headers=headers)
