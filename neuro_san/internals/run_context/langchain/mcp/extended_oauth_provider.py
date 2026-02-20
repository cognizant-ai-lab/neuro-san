
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
from typing import override
from urllib.parse import parse_qs

import httpx
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth.exceptions import OAuthTokenError
from mcp.client.auth.utils import handle_token_response_scopes
from mcp.shared.auth import OAuthToken
from pydantic import ValidationError


class ExtendedOauthClientProvider(OAuthClientProvider):
    """
    This class serves as the base implementation for OAuth client providers in the LangChain MCP adapter.
    It extends the standard OAuthClientProvider from the MCP SDK to support non-standard token responses.

    OAuthClientProvider itself extends httpx.Auth and is designed to handle custom authentication schemes.
    It overrides the async_auth_flow method, while the remaining helper methods are private.

    Key Methods:
    - async_auth_flow() - Entry point triggered on every HTTP request
    - _initialize() - Loads client info and tokens from storage (overridden by subclasses)
    - _perform_authorization() - Handles the authorization step (overridden by subclasses)

    The authentication flow proceeds as follows:
    1. When an HTTP request is sent to an MCP server, the async_auth_flow method is triggered.
    2. The provider attempts to load client information and tokens from storage. This logic is implemented in
    the _initialize() method, which is overridden in both ClientCredentialsOauthProvider and RefreshTokenOauthProvider.
    3. If the server responds with 401 Unauthorized, the provider attempts metadata discovery, including:
        - Protected Resource Metadata
        - OAuth Authorization Server Metadata
    4. The client is then either dynamically registered with the authorization server or identified using
    a URL-based client ID (CIMD).
    5. The authorization step is performed via the _perform_authorization() method. In the RefreshTokenOauthProvider,
    this method is overridden to exchange a refresh token (along with client credentials) for a new access token,
    instead of initiating an interactive user authorization flow.
    6. If the server responds with 403 Forbidden, the provider attempts to update the scopes from
    the protected resource metadata.
    7. Retry the authentication flow with the new scopes or tokens.

    The primary reason for extending this class rather than using it directly is to customize
    the token response handling logic. Specifically, we add support for both JSON and form-encoded token responses.

    See https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/client/auth/oauth2.py.
    """

    @override
    async def _handle_token_response(self, response: httpx.Response) -> None:
        """
        Handle token exchange response with multiple format support.
        Tries JSON first (standard), then falls back to form-encoded format.
        """
        if response.status_code not in {200, 201}:
            body: bytes = await response.aread()
            body_text: str = body.decode("utf-8")
            raise OAuthTokenError(f"Token exchange failed ({response.status_code}): {body_text}")

        # Try JSON first (standard OAuth format)
        try:
            token_response: OAuthToken = await handle_token_response_scopes(response)
        except OAuthTokenError:
            # Fall back to form-encoded format
            # This is the part we added to support non-standard token responses.
            try:
                token_response = await self._parse_form_token_response(response)
            except (ValueError, KeyError, ValidationError) as errors:
                raise OAuthTokenError(
                    f"Failed to parse token response in both JSON and form formats: {errors}") from errors

        # Store tokens in context
        self.context.current_tokens = token_response
        self.context.update_token_expiry(token_response)
        await self.context.storage.set_tokens(token_response)

    async def _parse_form_token_response(self, response: httpx.Response) -> OAuthToken:
        """
        Parse application/x-www-form-urlencoded token response.

        This is our own implementation since the MCP SDK only supports JSON responses.
        """
        content: bytes = await response.aread()
        body_text: str = content.decode("utf-8")
        # Parse form data
        params: Dict[str, Any] = parse_qs(body_text)

        # Extract token data (values are lists, take first element)
        token_data = {
            "access_token": params.get("access_token", [None])[0],
            "token_type": params.get("token_type", ["Bearer"])[0],
        }

        # Optional fields
        if "expires_in" in params:
            token_data["expires_in"] = int(params["expires_in"][0])

        if "refresh_token" in params and params["refresh_token"][0]:
            token_data["refresh_token"] = params["refresh_token"][0]

        if "scope" in params and params["scope"][0]:
            token_data["scope"] = params["scope"][0]

        # Validate required fields
        if not token_data["access_token"]:
            raise ValueError("Missing access_token in response")

        return OAuthToken(**token_data)
