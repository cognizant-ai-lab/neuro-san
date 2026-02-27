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

import pytest
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken

from neuro_san.internals.run_context.langchain.mcp.sly_data_token_storage import SlyDataTokenStorage


class TestSlyDataTokenStorage:
    """Test suite for SlyDataTokenStorage class"""

    @pytest.fixture
    def valid_token_dict(self):
        """Create valid token dictionary"""
        return {
            "access_token": "test_access_token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "test_refresh_token"
        }

    @pytest.fixture
    def valid_client_info_dict(self):
        """Create valid client info dictionary"""
        return {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "grant_types": ["client_credentials"],
            "token_endpoint_auth_method": "client_secret_basic",
            # Not used in client credentials flow, but required for OAuthClientInformationFull validation
            "redirect_uris": None
        }

    @pytest.fixture
    def storage_with_data(self, valid_client_info_dict, valid_token_dict):
        """Create storage with valid data"""
        return SlyDataTokenStorage(
            client_info=valid_client_info_dict.copy(),
            tokens=valid_token_dict.copy()
        )

    @pytest.fixture
    def storage_empty(self):
        """Create storage with empty data"""
        return SlyDataTokenStorage(client_info={}, tokens={})

    def test_init(self, valid_client_info_dict, valid_token_dict):
        """Test storage initialization"""
        storage = SlyDataTokenStorage(
            client_info=valid_client_info_dict,
            tokens=valid_token_dict
        )

        assert storage.client_info == valid_client_info_dict
        assert storage.tokens == valid_token_dict
        assert storage.logger is not None

    @pytest.mark.asyncio
    async def test_get_tokens_valid(self, storage_with_data):
        """Test getting valid tokens"""
        tokens = await storage_with_data.get_tokens()

        assert isinstance(tokens, OAuthToken)
        assert tokens.access_token == "test_access_token"
        assert tokens.token_type == "Bearer"
        assert tokens.expires_in == 3600
        assert tokens.refresh_token == "test_refresh_token"

    @pytest.mark.asyncio
    async def test_get_tokens_empty(self, storage_empty):
        """Test getting tokens when storage is empty"""
        tokens = await storage_empty.get_tokens()

        assert tokens is None

    @pytest.mark.asyncio
    async def test_get_tokens_invalid_data(self, caplog):
        """Test getting tokens with invalid data"""
        storage = SlyDataTokenStorage(
            client_info={},
            tokens={"invalid": "data"}  # Missing required fields
        )

        tokens = await storage.get_tokens()

        assert tokens is None
        assert "Failed to load token from sly data" in caplog.text

    @pytest.mark.asyncio
    async def test_get_tokens_dict(self, storage_with_data, valid_token_dict):
        """Test getting raw token dictionary"""
        tokens_dict = await storage_with_data.get_tokens_dict()

        assert tokens_dict == valid_token_dict

    @pytest.mark.asyncio
    async def test_set_tokens(self, storage_empty, valid_token_dict):
        """Test setting tokens"""
        oauth_token = OAuthToken(**valid_token_dict)

        await storage_empty.set_tokens(oauth_token)

        assert storage_empty.tokens["access_token"] == "test_access_token"
        assert storage_empty.tokens["token_type"] == "Bearer"
        assert storage_empty.tokens["expires_in"] == 3600
        assert storage_empty.tokens["refresh_token"] == "test_refresh_token"

    @pytest.mark.asyncio
    async def test_set_tokens_clears_existing(self, storage_with_data):
        """Test that setting tokens clears existing tokens"""
        new_token = OAuthToken(
            access_token="new_access_token",
            token_type="Bearer",
            expires_in=7200
        )

        await storage_with_data.set_tokens(new_token)

        assert storage_with_data.tokens["access_token"] == "new_access_token"
        assert storage_with_data.tokens["expires_in"] == 7200

    @pytest.mark.asyncio
    async def test_set_tokens_error_handling(self, storage_empty, caplog):
        """Test error handling when setting invalid tokens"""
        # Create a mock that will cause AttributeError
        invalid_token = None

        # This should trigger error handling
        await storage_empty.set_tokens(invalid_token)

        assert "Failed to save tokens in sly data" in caplog.text

    @pytest.mark.asyncio
    async def test_get_client_info_valid(self, storage_with_data):
        """Test getting valid client info"""
        client_info = await storage_with_data.get_client_info()

        assert isinstance(client_info, OAuthClientInformationFull)
        assert client_info.client_id == "test_client_id"
        assert client_info.client_secret == "test_client_secret"

    @pytest.mark.asyncio
    async def test_get_client_info_empty(self, storage_empty):
        """Test getting client info when storage is empty"""
        client_info = await storage_empty.get_client_info()

        assert client_info is None

    @pytest.mark.asyncio
    async def test_get_client_info_invalid_data(self, caplog):
        """Test getting client info with invalid data"""
        storage = SlyDataTokenStorage(
            client_info={"invalid": "data"},  # Missing required fields
            tokens={}
        )

        client_info = await storage.get_client_info()

        assert client_info is None
        assert "Failed to instantiate OAuthClientInformationFull" in caplog.text

    @pytest.mark.asyncio
    async def test_get_client_info_dict(self, storage_with_data, valid_client_info_dict):
        """Test getting raw client info dictionary"""
        client_info_dict = await storage_with_data.get_client_info_dict()

        assert client_info_dict == valid_client_info_dict

    @pytest.mark.asyncio
    async def test_set_client_info(self, storage_empty):
        """Test setting client info"""
        client_info = OAuthClientInformationFull(
            client_id="new_client_id",
            client_secret="new_client_secret",
            grant_types=["authorization_code"],
            token_endpoint_auth_method="client_secret_post",
            # Not used in client credentials flow, but required for OAuthClientInformationFull validation
            redirect_uris=None
        )

        await storage_empty.set_client_info(client_info)

        assert storage_empty.client_info["client_id"] == "new_client_id"
        assert storage_empty.client_info["client_secret"] == "new_client_secret"

    @pytest.mark.asyncio
    async def test_set_client_info_clears_existing(self, storage_with_data):
        """Test that setting client info clears existing data"""
        new_client_info = OAuthClientInformationFull(
            client_id="new_id",
            # Not used in client credentials flow, but required for OAuthClientInformationFull validation
            redirect_uris=None
        )

        await storage_with_data.set_client_info(new_client_info)

        assert storage_with_data.client_info["client_id"] == "new_id"

    @pytest.mark.asyncio
    async def test_set_client_info_error_handling(self, storage_empty, caplog):
        """Test error handling when setting invalid client info"""
        # This should trigger error handling
        await storage_empty.set_client_info(None)

        assert "Failed to save client info in sly data" in caplog.text

    @pytest.mark.asyncio
    async def test_tokens_reference_preserved(self, valid_token_dict):
        """Test that tokens dictionary reference is preserved"""
        token_dict = valid_token_dict.copy()
        storage = SlyDataTokenStorage(client_info={}, tokens=token_dict)

        # Modify through storage
        oauth_token = OAuthToken(
            access_token="updated_token",
            token_type="Bearer",
            expires_in=1800
        )
        await storage.set_tokens(oauth_token)

        # Check that original reference was updated
        assert token_dict["access_token"] == "updated_token"
        assert token_dict["expires_in"] == 1800

    @pytest.mark.asyncio
    async def test_client_info_reference_preserved(self, valid_client_info_dict):
        """Test that client info dictionary reference is preserved"""
        client_dict = valid_client_info_dict.copy()
        storage = SlyDataTokenStorage(client_info=client_dict, tokens={})

        # Modify through storage
        new_client_info = OAuthClientInformationFull(
            client_id="updated_id",
            # Not used in client credentials flow, but required for OAuthClientInformationFull validation
            redirect_uris=None
        )
        await storage.set_client_info(new_client_info)

        # Check that original reference was updated
        assert client_dict["client_id"] == "updated_id"
