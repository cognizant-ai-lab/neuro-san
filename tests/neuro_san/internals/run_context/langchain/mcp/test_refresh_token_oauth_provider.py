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

from mcp.client.auth.exceptions import OAuthTokenError
from mcp.shared.auth import OAuthToken

from neuro_san.internals.run_context.langchain.mcp.refresh_token_oauth_provider import RefreshTokenOauthProvider


# pylint: disable=too-many-public-methods
class TestRefreshTokenOauthProvider:
    """Test suite for RefreshTokenOauthProvider class"""

    @pytest.fixture
    def mock_storage(self):
        """Create mock token storage"""
        storage = MagicMock()
        storage.get_tokens = AsyncMock(return_value=None)
        return storage

    @pytest.fixture
    def mock_token_with_refresh(self):
        """Create mock token with refresh token"""
        return OAuthToken(
            access_token="test_access_token",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="test_refresh_token"
        )

    @pytest.fixture
    def provider(self, mock_storage):
        """Create provider instance with basic credentials"""
        return RefreshTokenOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_client_id",
            client_secret="test_client_secret"
        )

    # pylint: disable=protected-access
    def test_init_with_minimal_params(self, mock_storage):
        """Test initialization with minimal parameters"""
        provider = RefreshTokenOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id"
        )

        assert provider._fixed_client_info.client_id == "test_id"
        assert provider._fixed_client_info.client_secret is None
        assert provider._fixed_client_info.grant_types == ["refresh_token"]
        assert provider._fixed_client_info.token_endpoint_auth_method == "client_secret_basic"
        assert provider._fixed_client_info.scope is None
        assert provider.token_endpoint is None
        assert provider.context.timeout == 300.0

    def test_init_with_all_params(self, mock_storage):
        """Test initialization with all parameters"""
        provider = RefreshTokenOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            token_endpoint="https://auth.example.com/token",
            token_endpoint_auth_method="client_secret_post",
            scopes="read write",
            timeout=600.0
        )

        assert provider._fixed_client_info.client_id == "test_id"
        assert provider._fixed_client_info.client_secret == "test_secret"
        assert provider.token_endpoint == "https://auth.example.com/token"
        assert provider._fixed_client_info.token_endpoint_auth_method == "client_secret_post"
        assert provider._fixed_client_info.scope == "read write"
        assert provider.context.timeout == 600.0

    def test_init_without_client_secret(self, mock_storage):
        """Test initialization without client_secret (some servers don't require it)"""
        provider = RefreshTokenOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret=None
        )

        assert provider._fixed_client_info.client_secret is None

    def test_init_with_none_auth_method(self, mock_storage):
        """Test initialization with None auth method"""
        provider = RefreshTokenOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            token_endpoint_auth_method=None
        )

        assert provider._fixed_client_info.token_endpoint_auth_method is None

    def test_fixed_client_info_structure(self, provider):
        """Test that fixed client info has correct structure"""
        client_info = provider._fixed_client_info

        assert client_info.redirect_uris is None
        assert client_info.grant_types == ["refresh_token"]
        assert hasattr(client_info, "client_id")
        assert hasattr(client_info, "client_secret")

    def test_client_metadata_structure(self, provider):
        """Test that client metadata is correctly configured"""
        assert provider.context.client_metadata.grant_types == ["refresh_token"]
        assert provider.context.client_metadata.redirect_uris is None

    @pytest.mark.asyncio
    async def test_initialize_loads_tokens(self, provider, mock_storage, mock_token_with_refresh):
        """Test that _initialize loads tokens from storage"""
        mock_storage.get_tokens.return_value = mock_token_with_refresh

        await provider._initialize()

        assert provider.context.current_tokens == mock_token_with_refresh
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
        mock_storage.get_tokens.assert_called_once()

    @pytest.mark.asyncio
    @patch.object(RefreshTokenOauthProvider, '_refresh_token')
    async def test_perform_authorization_calls_refresh_token(self, mock_refresh, provider):
        """Test that _perform_authorization calls refresh token method"""
        mock_request = MagicMock()
        mock_refresh.return_value = mock_request

        result = await provider._perform_authorization()

        assert result == mock_request
        mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_token_creates_correct_request(self, provider, mock_token_with_refresh):
        """Test that refresh token creates correct HTTP request"""
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh

        request = await provider._refresh_token()

        assert request.method == "POST"
        request_body = str(request.content)
        assert "grant_type" in request_body
        assert "refresh_token" in request_body
        assert "client_id" in request_body

    @pytest.mark.asyncio
    async def test_refresh_token_raises_error_when_no_refresh_token(self, provider):
        """Test that error is raised when no refresh token available"""
        await provider._initialize()
        provider.context.current_tokens = OAuthToken(
            access_token="test_token",
            token_type="Bearer",
            expires_in=3600
            # No refresh_token
        )

        with pytest.raises(OAuthTokenError, match="No refresh token available"):
            await provider._refresh_token()

    @pytest.mark.asyncio
    async def test_refresh_token_raises_error_when_no_tokens(self, provider):
        """Test that error is raised when no tokens at all"""
        await provider._initialize()
        provider.context.current_tokens = None

        with pytest.raises(OAuthTokenError, match="No refresh token available"):
            await provider._refresh_token()

    @pytest.mark.asyncio
    async def test_refresh_token_raises_error_when_no_client_info(self, provider, mock_token_with_refresh):
        """Test that error is raised when no client info available"""
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh
        provider.context.client_info = None

        with pytest.raises(OAuthTokenError, match="No client info available"):
            await provider._refresh_token()

    @pytest.mark.asyncio
    async def test_refresh_token_raises_error_when_no_client_id(self, provider, mock_token_with_refresh):
        """Test that error is raised when client_id is missing"""
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh
        provider.context.client_info.client_id = None

        with pytest.raises(OAuthTokenError, match="No client info available"):
            await provider._refresh_token()

    @pytest.mark.asyncio
    async def test_refresh_token_uses_provided_endpoint(self, mock_storage, mock_token_with_refresh):
        """Test that provided token_endpoint is used"""
        provider = RefreshTokenOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            token_endpoint="https://custom.auth.com/oauth/token"
        )
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh

        request = await provider._refresh_token()

        assert str(request.url) == "https://custom.auth.com/oauth/token"

    @pytest.mark.asyncio
    async def test_refresh_token_content_type_header(self, provider, mock_token_with_refresh):
        """Test that correct Content-Type header is set"""
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh

        request = await provider._refresh_token()

        assert request.headers.get("Content-Type") == "application/x-www-form-urlencoded"

    @pytest.mark.asyncio
    async def test_refresh_token_uses_client_secret_basic_auth(self, mock_storage, mock_token_with_refresh):
        """Test that client_secret_basic method is used correctly"""
        provider = RefreshTokenOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            token_endpoint_auth_method="client_secret_basic"
        )
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh

        request = await provider._refresh_token()

        # client_secret_basic should use Authorization header
        assert "Authorization" in request.headers or "authorization" in request.headers

    @pytest.mark.asyncio
    async def test_refresh_token_uses_client_secret_post(self, mock_storage, mock_token_with_refresh):
        """Test that client_secret_post method includes secret in body"""
        provider = RefreshTokenOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret="test_secret",
            token_endpoint_auth_method="client_secret_post"
        )
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh

        request = await provider._refresh_token()

        # client_secret_post should include client_secret in request body
        request_body = str(request.content)
        assert "client_secret" in request_body or request.method == "POST"

    @pytest.mark.asyncio
    @patch.object(RefreshTokenOauthProvider, '_get_token_endpoint')
    async def test_refresh_token_prefers_provided_endpoint(
        self, mock_get_endpoint, mock_storage, mock_token_with_refresh
    ):
        """Test that provided endpoint is preferred over discovered endpoint"""
        provider = RefreshTokenOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            token_endpoint="https://fallback.auth.com/token"
        )
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh

        # Mock that discovery found an endpoint
        mock_get_endpoint.return_value = "https://discovered.auth.com/token"

        request = await provider._refresh_token()

        # Should use provided endpoint, not discovered one
        assert str(request.url) == "https://fallback.auth.com/token"

    @pytest.mark.asyncio
    @patch.object(RefreshTokenOauthProvider, '_get_token_endpoint')
    async def test_refresh_token_falls_back_to_discovered_endpoint(
        self, mock_get_endpoint, mock_storage, mock_token_with_refresh
    ):
        """Test fallback to discovered endpoint when provided endpoint is None"""
        provider = RefreshTokenOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            token_endpoint=None
        )
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh

        # Mock that discovery found nothing
        mock_get_endpoint.return_value = "https://mcp.example.com/token"

        request = await provider._refresh_token()

        # Should use discovered endpoint as fallback
        assert str(request.url) == "https://mcp.example.com/token"

    @pytest.mark.asyncio
    async def test_refresh_token_includes_client_id(self, provider, mock_token_with_refresh):
        """Test that client_id is included in refresh request"""
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh

        request = await provider._refresh_token()

        request_body = str(request.content)
        assert "test_client_id" in request_body

    @pytest.mark.asyncio
    async def test_refresh_token_includes_refresh_token_value(self, provider, mock_token_with_refresh):
        """Test that refresh_token value is included in request"""
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh

        request = await provider._refresh_token()

        request_body = str(request.content)
        assert "test_refresh_token" in request_body

    @pytest.mark.asyncio
    async def test_refresh_token_works_without_client_secret(self, mock_storage, mock_token_with_refresh):
        """Test that refresh works without client_secret (some OAuth servers allow this)"""
        provider = RefreshTokenOauthProvider(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            client_id="test_id",
            client_secret=None
        )
        await provider._initialize()
        provider.context.current_tokens = mock_token_with_refresh

        # Should not raise an error
        request = await provider._refresh_token()

        assert request.method == "POST"
        request_body = str(request.content)
        assert "grant_type" in request_body
        assert "refresh_token" in request_body
