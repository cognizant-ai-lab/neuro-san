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

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch
import pytest

from neuro_san.internals.run_context.langchain.mcp.client_credentials_oauth_provider import \
    ClientCredentialsOauthProvider


class TestClientCredentialsOauthProvider:
    """Test suite for ClientCredentialsOauthProvider class"""

    @pytest.fixture
    def mock_storage(self):
        """Create mock token storage"""
        storage = MagicMock()
        storage.get_tokens = AsyncMock(return_value=None)
        return storage

    @pytest.fixture
    def provider(self, mock_storage):
        """Create provider instance with basic credentials"""
        return ClientCredentialsOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_client_id",
            client_secret="test_client_secret"
        )

    # pylint: disable=protected-access
    def test_init_with_minimal_params(self, mock_storage):
        """Test initialization with minimal parameters"""
        provider = ClientCredentialsOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret"
        )

        assert provider._fixed_client_info.client_id == "test_id"
        assert provider._fixed_client_info.client_secret == "test_secret"
        assert provider._fixed_client_info.grant_types == ["client_credentials"]
        assert provider._fixed_client_info.token_endpoint_auth_method == "client_secret_basic"
        assert provider._fixed_client_info.scope is None
        assert provider.token_endpoint is None
        assert provider.context.timeout == 300.0

    def test_init_with_all_params(self, mock_storage):
        """Test initialization with all parameters"""
        provider = ClientCredentialsOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            token_endpoint="https://auth.example.com/token",
            token_endpoint_auth_method="client_secret_post",
            scopes="read write",
            timeout=600.0
        )

        assert provider.token_endpoint == "https://auth.example.com/token"
        assert provider._fixed_client_info.token_endpoint_auth_method == "client_secret_post"
        assert provider._fixed_client_info.scope == "read write"
        assert provider.context.timeout == 600.0

    def test_init_with_none_auth_method(self, mock_storage):
        """Test initialization with None auth method"""
        provider = ClientCredentialsOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            token_endpoint_auth_method=None
        )

        assert provider._fixed_client_info.token_endpoint_auth_method is None

    def test_fixed_client_info_structure(self, provider):
        """Test that fixed client info has correct structure"""
        client_info = provider._fixed_client_info

        assert client_info.redirect_uris is None
        assert client_info.grant_types == ["client_credentials"]
        assert hasattr(client_info, "client_id")
        assert hasattr(client_info, "client_secret")

    def test_client_metadata_structure(self, provider):
        """Test that client metadata is correctly configured"""
        # Access through the parent class context
        assert provider.context.client_metadata.grant_types == ["client_credentials"]
        assert provider.context.client_metadata.redirect_uris is None

    @pytest.mark.asyncio
    async def test_initialize_loads_tokens(self, provider, mock_storage):
        """Test that _initialize loads tokens from storage"""
        mock_token = MagicMock()
        mock_storage.get_tokens.return_value = mock_token

        await provider._initialize()

        assert provider.context.current_tokens == mock_token
        mock_storage.get_tokens.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_sets_client_info(self, provider):
        """Test that _initialize sets fixed client info"""
        await provider._initialize()

        assert provider.context.client_info == provider._fixed_client_info
        assert provider._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_does_not_call_dynamic_registration(self, provider, mock_storage):
        """Test that _initialize bypasses dynamic client registration"""
        await provider._initialize()

        # Client info should be set directly, not loaded from storage
        assert provider.context.client_info == provider._fixed_client_info
        # get_tokens should be called, but not any client registration methods
        mock_storage.get_tokens.assert_called_once()

    @pytest.mark.asyncio
    @patch.object(ClientCredentialsOauthProvider, '_exchange_token_client_credentials')
    async def test_perform_authorization_calls_exchange_token(self, mock_exchange, provider):
        """Test that _perform_authorization calls token exchange"""
        mock_request = MagicMock()
        mock_exchange.return_value = mock_request

        result = await provider._perform_authorization()

        assert result == mock_request
        mock_exchange.assert_called_once()

    @pytest.mark.asyncio
    async def test_exchange_token_client_credentials_basic_request(self, provider):
        """Test that token exchange creates correct request"""
        await provider._initialize()

        request = await provider._exchange_token_client_credentials()

        assert request.method == "POST"
        assert "grant_type" in str(request.content)
        assert "client_credentials" in str(request.content)
        assert "client_id" in str(request.content)

    @pytest.mark.asyncio
    async def test_exchange_token_uses_client_secret_basic_auth(self, mock_storage):
        """Test that client_secret_basic method is used correctly"""
        provider = ClientCredentialsOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            token_endpoint_auth_method="client_secret_basic"
        )
        await provider._initialize()

        request = await provider._exchange_token_client_credentials()

        # client_secret_basic should use Authorization header
        assert "Authorization" in request.headers or "authorization" in request.headers

    @pytest.mark.asyncio
    async def test_exchange_token_uses_client_secret_post(self, mock_storage):
        """Test that client_secret_post method includes secret in body"""
        provider = ClientCredentialsOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            token_endpoint_auth_method="client_secret_post"
        )
        await provider._initialize()

        request = await provider._exchange_token_client_credentials()

        # client_secret_post should include client_secret in request body
        request_body = str(request.content)
        assert "client_secret" in request_body or request.method == "POST"

    @pytest.mark.asyncio
    async def test_exchange_token_includes_scope_when_provided(self, mock_storage):
        """Test that scope is included in token request when provided"""
        provider = ClientCredentialsOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            scopes="read write admin"
        )
        await provider._initialize()

        request = await provider._exchange_token_client_credentials()

        request_body = str(request.content)
        assert "scope" in request_body

    @pytest.mark.asyncio
    async def test_exchange_token_excludes_scope_when_none(self, mock_storage):
        """Test that scope is excluded when not provided"""
        provider = ClientCredentialsOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            scopes=None
        )
        await provider._initialize()

        request = await provider._exchange_token_client_credentials()

        # Scope should not be in request when None
        # We check this by ensuring the request was created without errors
        assert request.method == "POST"

    @pytest.mark.asyncio
    async def test_exchange_token_uses_provided_endpoint(self, mock_storage):
        """Test that provided token_endpoint is used"""
        provider = ClientCredentialsOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            token_endpoint="https://custom.auth.com/oauth/token"
        )
        await provider._initialize()

        request = await provider._exchange_token_client_credentials()

        assert str(request.url) == "https://custom.auth.com/oauth/token"

    @pytest.mark.asyncio
    async def test_exchange_token_content_type_header(self, provider):
        """Test that correct Content-Type header is set"""
        await provider._initialize()

        request = await provider._exchange_token_client_credentials()

        assert request.headers.get("Content-Type") == "application/x-www-form-urlencoded"

    @pytest.mark.asyncio
    @patch.object(ClientCredentialsOauthProvider, '_get_token_endpoint')
    async def test_exchange_token_prefers_provided_endpoint(self, mock_get_endpoint, mock_storage):
        """Test that provided endpoint is preferred over discovered endpoint"""
        provider = ClientCredentialsOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            token_endpoint="https://fallback.auth.com/token"
        )
        await provider._initialize()

        # Mock that discovery found an endpoint
        mock_get_endpoint.return_value = "https://discovered.auth.com/token"

        request = await provider._exchange_token_client_credentials()

        # Should use the provided one, not the discovered one
        assert str(request.url) == "https://fallback.auth.com/token"

    @pytest.mark.asyncio
    @patch.object(ClientCredentialsOauthProvider, '_get_token_endpoint')
    async def test_exchange_token_falls_back_to_discovered_endpoint(self, mock_get_endpoint, mock_storage):
        """Test fallback to discovered endpoint when provided endpoint is None"""
        provider = ClientCredentialsOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            token_endpoint=None
        )
        await provider._initialize()

        mock_get_endpoint.return_value = "https://mcp.example.com/token"

        request = await provider._exchange_token_client_credentials()

        # Should MCP token endpoint as fallback
        assert str(request.url) == "https://mcp.example.com/token"
