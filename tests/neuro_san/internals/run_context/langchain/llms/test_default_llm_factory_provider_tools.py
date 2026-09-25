# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT
"""Tests for provider-native tools in DefaultLlmFactory."""
from unittest import TestCase
from unittest.mock import MagicMock

import pytest

from neuro_san.internals.run_context.langchain.llms.anthropic_llm_policy import AnthropicLlmPolicy
from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory
from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy
from neuro_san.internals.run_context.langchain.llms.openai_llm_policy import OpenAILlmPolicy


pytestmark = [pytest.mark.non_default_llm_provider, pytest.mark.ollama]


class TestDefaultLlmFactoryProviderTools(TestCase):
    """Verify custom-class filtering and fallback provider compatibility."""

    @staticmethod
    def _resources(policy: LlmPolicy) -> MagicMock:
        """
        Create mocked resources carrying the requested provider policy.

        :param policy: The provider policy returned by the resources.
        :return: Mocked LangChain LLM resources.
        """
        resources = MagicMock()
        resources.get_llm_policy.return_value = policy
        return resources

    def test_user_class_does_not_receive_provider_tools(self) -> None:
        """provider_tools is run-context configuration, not a model constructor argument."""
        factory = DefaultLlmFactory()
        class_path = "neuro_san.test.llms.chat_mock_llm.ChatMockLlm"

        model = factory.create_base_chat_model_from_user_class(
            class_path,
            {
                "class": class_path,
                "model": "mock-model",
                "provider_tools": [{"type": "web_search"}],
            },
        )

        self.assertEqual("mock-model", model.model_name)

    def test_mixed_provider_fallbacks_rejected(self) -> None:
        """A provider tool cannot be broadcast across unlike provider policies."""
        factory = DefaultLlmFactory()
        factory.create_llm = MagicMock(side_effect=[
            self._resources(OpenAILlmPolicy()),
            self._resources(AnthropicLlmPolicy()),
        ])
        config = {
            "provider_tools": [{"type": "web_search"}],
            "fallbacks": [{"model_name": "first"}, {"model_name": "second"}],
        }

        with self.assertRaisesRegex(ValueError, "AnthropicLlmPolicy, OpenAILlmPolicy"):
            factory.create_llm_with_fallbacks(config)

    def test_same_provider_fallbacks_allowed(self) -> None:
        """Fallback models using the same policy type remain supported."""
        factory = DefaultLlmFactory()
        main = self._resources(OpenAILlmPolicy())
        fallback = self._resources(OpenAILlmPolicy())
        factory.create_llm = MagicMock(side_effect=[main, fallback])
        config = {
            "provider_tools": [{"type": "web_search"}],
            "fallbacks": [{"model_name": "first"}, {"model_name": "second"}],
        }

        result = factory.create_llm_with_fallbacks(config)

        self.assertIs(main, result)
        main.add_fallback_resources.assert_called_once_with([fallback])

    def test_empty_provider_tools_allows_mixed_fallbacks(self) -> None:
        """The provider-type restriction applies only to a non-empty declaration."""
        factory = DefaultLlmFactory()
        main = self._resources(OpenAILlmPolicy())
        fallback = self._resources(AnthropicLlmPolicy())
        factory.create_llm = MagicMock(side_effect=[main, fallback])
        config = {
            "provider_tools": [],
            "fallbacks": [{"model_name": "first"}, {"model_name": "second"}],
        }

        result = factory.create_llm_with_fallbacks(config)

        self.assertIs(main, result)
