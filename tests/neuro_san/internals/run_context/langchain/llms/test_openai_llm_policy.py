
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
"""
Unit tests for OpenAILlmPolicy.
"""
import asyncio
from unittest.mock import MagicMock

from neuro_san.internals.run_context.langchain.llms.openai_llm_policy import OpenAILlmPolicy


class TestOpenAILlmPolicy:
    """
    Test cases for OpenAILlmPolicy.
    """

    def test_create_llm_config_keys(self):
        """
        Test that create_llm reads the correct config keys for the client-supplied kwargs group,
        specifically ensuring openai_proxy reads 'openai_proxy' and not 'openai_organization'.
        """
        captured_kwargs = {}

        def mock_chat_openai(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock()

        policy = OpenAILlmPolicy()
        policy.resolver.resolve_class_in_module = MagicMock(return_value=mock_chat_openai)

        config = {
            "openai_api_key": "sk-test-key",
            "openai_api_base": "https://custom.api.com",
            "openai_organization": "org-12345",
            "openai_proxy": "http://proxy.test:8080",
            "request_timeout": 60,
            "max_retries": 3,
            "temperature": 0.7,
        }

        policy.create_llm(config=config, model_name="gpt-4o", client=None)

        assert captured_kwargs.get("openai_organization") == "org-12345"
        assert captured_kwargs.get("openai_proxy") == "http://proxy.test:8080"
        assert captured_kwargs.get("openai_api_key") == "sk-test-key"
        assert captured_kwargs.get("openai_api_base") == "https://custom.api.com"
        assert captured_kwargs.get("request_timeout") == 60
        assert captured_kwargs.get("max_retries") == 3

    def test_create_llm_calls_get_value_or_env_keys(self):
        """
        Verify each get_value_or_env call for the optional connection parameters
        passes the corresponding config key, env var name, and client instance.
        """
        policy = OpenAILlmPolicy()
        policy.resolver.resolve_class_in_module = MagicMock(return_value=MagicMock())

        calls = []
        original_get_value_or_env = policy.get_value_or_env

        def spy_get_value_or_env(config, key, env_key, none_obj=None):
            calls.append((key, env_key, none_obj))
            return original_get_value_or_env(config, key, env_key, none_obj)

        policy.get_value_or_env = spy_get_value_or_env

        dummy_client = object()
        config = {
            "openai_organization": "org-test",
            "openai_proxy": "http://proxy.test:8080",
        }

        policy.create_llm(config=config, model_name="gpt-4o", client=dummy_client)

        expected_calls = [
            ("openai_api_key", "OPENAI_API_KEY", dummy_client),
            ("openai_api_base", "OPENAI_API_BASE", dummy_client),
            ("openai_organization", "OPENAI_ORG_ID", dummy_client),
            ("openai_proxy", "OPENAI_PROXY", dummy_client),
            ("request_timeout", None, dummy_client),
            ("max_retries", None, dummy_client),
        ]

        for expected in expected_calls:
            assert expected in calls, f"Expected get_value_or_env call {expected} not found in {calls}"

    def test_create_llm_with_client_forces_none(self):
        """
        When a client is provided, the connection parameters must all be None.
        """
        captured_kwargs = {}

        def mock_chat_openai(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock()

        policy = OpenAILlmPolicy()
        policy.resolver.resolve_class_in_module = MagicMock(return_value=mock_chat_openai)

        dummy_client = object()
        config = {
            "openai_api_key": "sk-test-key",
            "openai_api_base": "https://custom.api.com",
            "openai_organization": "org-12345",
            "openai_proxy": "http://proxy.test:8080",
            "request_timeout": 60,
            "max_retries": 3,
        }

        policy.create_llm(config=config, model_name="gpt-4o", client=dummy_client)

        assert captured_kwargs.get("openai_api_key") is None
        assert captured_kwargs.get("openai_api_base") is None
        assert captured_kwargs.get("openai_organization") is None
        assert captured_kwargs.get("openai_proxy") is None
        assert captured_kwargs.get("request_timeout") is None
        assert captured_kwargs.get("max_retries") is None

    def test_delete_resources(self):
        """
        Test that delete_resources clears the async_openai_client reference.
        """
        policy = OpenAILlmPolicy()
        policy.async_openai_client = MagicMock()
        asyncio.run(policy.delete_resources())
        assert policy.async_openai_client is None
