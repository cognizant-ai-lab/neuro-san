
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

from collections.abc import Awaitable
from collections.abc import Callable
from typing import Literal
from typing import Tuple

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthClientMetadata
from mcp.shared.auth import OAuthMetadata
from pydantic import AnyUrl

from neuro_san.internals.run_context.langchain.mcp.extended_oauth_provider import ExtendedOauthClientProvider


class AuthorizationCodeOauthProvider(ExtendedOauthClientProvider):
    """
    OAuth provider for authorization_code grant with pre-configured client_id and client_secret.
    Endpoints could be provided by users if discovery is not available.
    Adapted from
    https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/client/auth/extensions/client_credentials.py
    """

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        client_id: str,
        client_secret: str,
        authorization_endpoint: str = None,
        token_endpoint: str = None,
        token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = "client_secret_basic",
        redirect_handler: Callable[[str], Awaitable[None]] = None,
        callback_handler: Callable[[], Awaitable[Tuple[str]]] = None,
        callback_port: int = 3000,
        scopes: str = None,
    ) -> None:
        """Constructor"""
        # Build minimal client_metadata for the base class
        client_metadata = OAuthClientMetadata(
            redirect_uris=[f"http://localhost:{callback_port}/callback"],
            grant_types=["authorization_code", "refresh_token"],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scopes,
        )
        super().__init__(server_url, client_metadata, storage, redirect_handler, callback_handler, 300.0)
        # Store client_info to be set during _initialize - no dynamic registration needed
        self._fixed_client_info = OAuthClientInformationFull(
            redirect_uris=[f"http://localhost:{callback_port}/callback"],
            client_id=client_id,
            client_secret=client_secret,
            grant_types=["authorization_code", "refresh_token"],
            token_endpoint_auth_method=token_endpoint_auth_method,
            scope=scopes,
        )
        self.authorization_endpoint = authorization_endpoint
        self.token_endpoint = token_endpoint

    async def _initialize(self) -> None:
        """
        Load stored tokens, set pre-configured client_info, and inject authorization and token endpoints if available.
        """
        self.context.current_tokens = await self.context.storage.get_tokens()
        self.context.client_info = self._fixed_client_info
        if self.authorization_endpoint and self.token_endpoint:
            self.context.oauth_metadata = OAuthMetadata(
                issuer=AnyUrl(self.context.get_authorization_base_url(self.context.server_url)),
                authorization_endpoint=AnyUrl(self.authorization_endpoint),
                token_endpoint=AnyUrl(self.token_endpoint),
            )
        self._initialized = True
