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
import pytest

from neuro_san.internals.run_context.langchain.mcp.client_credentials_oauth_provider import \
    ClientCredentialsOauthProvider
from neuro_san.internals.run_context.langchain.mcp.oauth_provider_factory import OauthProviderFactory
from neuro_san.internals.run_context.langchain.mcp.refresh_token_oauth_provider import RefreshTokenOauthProvider


class TestOauthProviderFactory:
    """Test suite for OauthProviderFactory class"""

    @pytest.fixture
    def mock_storage(self):
        """Create mock token storage"""
        storage = MagicMock()
        storage.get_client_info_dict = AsyncMock()
        storage.get_tokens_dict = AsyncMock()
        return storage

    @pytest.fixture
    def factory(self, mock_storage):
        """Create factory instance"""
        return OauthProviderFactory(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            token_endpoint="https://auth.example.com/token",
            timeout=300.0
        )

    def test_init(self, mock_storage):
        """Test factory initialization"""
        factory = OauthProviderFactory(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            token_endpoint="https://auth.example.com/token",
            timeout=600.0
        )

        assert factory.server_url == "https://mcp.example.com/mcp"
        assert factory.storage == mock_storage
        assert factory.token_endpoint == "https://auth.example.com/token"
        assert factory.timeout == 600.0
        assert factory.logger is not None

    def test_init_with_defaults(self, mock_storage):
        """Test factory initialization with default values"""
        factory = OauthProviderFactory(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage
        )

        assert factory.token_endpoint is None
        assert factory.timeout == 300.0

    @pytest.mark.asyncio
    async def test_get_auth_returns_none_when_no_credentials(self, factory, mock_storage):
        """Test that get_auth returns None when no credentials available"""
        mock_storage.get_client_info_dict.return_value = {}
        mock_storage.get_tokens_dict.return_value = {}

        auth = await factory.get_auth()

        assert auth is None

    @pytest.mark.asyncio
    async def test_get_auth_returns_refresh_token_provider_when_refresh_token_available(
        self, factory, mock_storage
    ):
        """Test that refresh token provider is used when refresh token is available"""
        mock_storage.get_client_info_dict.return_value = {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret"
        }
        mock_storage.get_tokens_dict.return_value = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token"
        }

        auth = await factory.get_auth()

        assert isinstance(auth, RefreshTokenOauthProvider)

    @pytest.mark.asyncio
    async def test_get_auth_returns_client_credentials_provider_when_no_refresh_token(
        self, factory, mock_storage
    ):
        """Test that client credentials provider is used when no refresh token"""
        mock_storage.get_client_info_dict.return_value = {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret"
        }
        mock_storage.get_tokens_dict.return_value = {
            "access_token": "test_access_token"
            # No refresh_token
        }

        auth = await factory.get_auth()

        assert isinstance(auth, ClientCredentialsOauthProvider)

    @pytest.mark.asyncio
    async def test_get_auth_prioritizes_refresh_token_over_client_credentials(
        self, factory, mock_storage
    ):
        """Test that refresh token flow is prioritized over client credentials"""
        mock_storage.get_client_info_dict.return_value = {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret"
        }
        mock_storage.get_tokens_dict.return_value = {
            "refresh_token": "test_refresh_token"
        }

        auth = await factory.get_auth()

        # Should use refresh token provider, not client credentials
        assert isinstance(auth, RefreshTokenOauthProvider)

    # pylint: disable=protected-access
    @pytest.mark.asyncio
    async def test_create_client_credentials_provider_with_all_params(self, factory):
        """Test client credentials provider creation with all parameters"""
        credentials = {
            "client_id": "test_id",
            "client_secret": "test_secret",
            "token_endpoint_auth_method": "client_secret_post",
            "scope": "read write"
        }

        provider = await factory._create_client_credentials_provider(credentials)

        assert isinstance(provider, ClientCredentialsOauthProvider)
        assert provider._fixed_client_info.client_id == "test_id"
        assert provider._fixed_client_info.client_secret == "test_secret"
        assert provider._fixed_client_info.token_endpoint_auth_method == "client_secret_post"
        assert provider._fixed_client_info.scope == "read write"
        assert provider.token_endpoint == "https://auth.example.com/token"
        assert provider.context.timeout == 300.0

    @pytest.mark.asyncio
    async def test_create_client_credentials_provider_with_defaults(self, factory):
        """Test client credentials provider with default auth method"""
        credentials = {
            "client_id": "test_id",
            "client_secret": "test_secret"
        }

        provider = await factory._create_client_credentials_provider(credentials)

        assert provider._fixed_client_info.token_endpoint_auth_method == "client_secret_basic"
        assert provider._fixed_client_info.scope is None

    @pytest.mark.asyncio
    async def test_create_refresh_token_provider_with_all_params(self, factory):
        """Test refresh token provider creation with all parameters"""
        credentials = {
            "client_id": "test_id",
            "client_secret": "test_secret",
            "token_endpoint_auth_method": "client_secret_post",
            "scope": "read write"
        }

        provider = await factory._create_refresh_token_provider(credentials)

        assert isinstance(provider, RefreshTokenOauthProvider)
        assert provider._fixed_client_info.client_id == "test_id"
        assert provider._fixed_client_info.client_secret == "test_secret"
        assert provider._fixed_client_info.token_endpoint_auth_method == "client_secret_post"
        assert provider._fixed_client_info.scope == "read write"
        assert provider.token_endpoint == "https://auth.example.com/token"
        assert provider.context.timeout == 300.0

    @pytest.mark.asyncio
    async def test_create_refresh_token_provider_with_defaults(self, factory):
        """Test refresh token provider with default auth method"""
        credentials = {
            "client_id": "test_id",
            "client_secret": "test_secret"
        }

        provider = await factory._create_refresh_token_provider(credentials)

        assert provider._fixed_client_info.token_endpoint_auth_method == "client_secret_basic"
        assert provider._fixed_client_info.scope is None

    @pytest.mark.asyncio
    async def test_get_auth_handles_empty_tokens_dict(self, factory, mock_storage):
        """Test that empty tokens dict is handled correctly"""
        mock_storage.get_client_info_dict.return_value = {
            "client_id": "test_id",
            "client_secret": "test_secret"
        }
        mock_storage.get_tokens_dict.return_value = {}

        auth = await factory.get_auth()

        # Should fall back to client credentials (no refresh token)
        assert isinstance(auth, ClientCredentialsOauthProvider)

    @pytest.mark.asyncio
    async def test_get_auth_handles_none_refresh_token(self, factory, mock_storage):
        """Test that None refresh token is handled correctly"""
        mock_storage.get_client_info_dict.return_value = {
            "client_id": "test_id",
            "client_secret": "test_secret"
        }
        mock_storage.get_tokens_dict.return_value = {
            "refresh_token": None
        }

        auth = await factory.get_auth()

        # Should fall back to client credentials (None is falsy)
        assert isinstance(auth, ClientCredentialsOauthProvider)

    @pytest.mark.asyncio
    async def test_get_auth_handles_empty_string_refresh_token(self, factory, mock_storage):
        """Test that empty string refresh token is handled correctly"""
        mock_storage.get_client_info_dict.return_value = {
            "client_id": "test_id",
            "client_secret": "test_secret"
        }
        mock_storage.get_tokens_dict.return_value = {
            "refresh_token": ""
        }

        auth = await factory.get_auth()

        # Should fall back to client credentials (empty string is falsy)
        assert isinstance(auth, ClientCredentialsOauthProvider)

    @pytest.mark.asyncio
    async def test_factory_uses_provided_token_endpoint(self, mock_storage):
        """Test that factory passes token_endpoint to providers"""
        factory = OauthProviderFactory(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            token_endpoint="https://custom.auth.com/oauth/token"
        )

        mock_storage.get_client_info_dict.return_value = {"client_id": "test_id"}
        mock_storage.get_tokens_dict.return_value = {}

        provider = await factory.get_auth()

        assert provider.token_endpoint == "https://custom.auth.com/oauth/token"

    @pytest.mark.asyncio
    async def test_factory_uses_provided_timeout(self, mock_storage):
        """Test that factory passes timeout to providers"""
        factory = OauthProviderFactory(
            server_url="https://mcp.example.com/mcp",
            storage=mock_storage,
            timeout=600.0
        )

        mock_storage.get_client_info_dict.return_value = {"client_id": "test_id"}
        mock_storage.get_tokens_dict.return_value = {}

        provider = await factory.get_auth()

        assert provider.context.timeout == 600.0
