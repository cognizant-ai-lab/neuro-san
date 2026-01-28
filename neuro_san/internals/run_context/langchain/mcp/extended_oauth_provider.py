
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

from urllib.parse import parse_qs

import httpx
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth.exceptions import OAuthTokenError
from mcp.client.auth.utils import handle_token_response_scopes
from mcp.shared.auth import OAuthToken
from pydantic import ValidationError


class ExtendedOauthClientProvider(OAuthClientProvider):
    """
    Extended OAuthClientProvider that handles both JSON and form-encoded token responses.
    Tries JSON first (standard), then falls back to form-encoded format.

    See https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/client/auth/oauth2.py#L397.
    """

    async def _handle_token_response(self, response: httpx.Response) -> None:
        """Handle token exchange response with multiple format support."""
        if response.status_code not in {200, 201}:
            body = await response.aread()
            body_text = body.decode("utf-8")
            raise OAuthTokenError(f"Token exchange failed ({response.status_code}): {body_text}")

        # Try JSON first (standard OAuth format)
        try:
            token_response = await handle_token_response_scopes(response)
        except OAuthTokenError:
            # Fall back to form-encoded format
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
        """Parse application/x-www-form-urlencoded token response."""
        content = await response.aread()
        body_text = content.decode("utf-8")
        # Parse form data
        params = parse_qs(body_text)

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
