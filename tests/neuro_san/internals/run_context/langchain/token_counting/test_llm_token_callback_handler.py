
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

from time import time
from unittest.mock import patch
from typing import Dict

from langchain_community.callbacks.openai_info import TokenType
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import LLMResult
import pytest

from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import LlmTokenCallbackHandler


class TestLlmTokenCallbackHandler:
    """Test cases for the LlmTokenCallbackHandler.calculate_token_costs method."""

    @pytest.fixture
    def handler_with_empty_infos(self):
        """Create a handler with empty llm_infos."""
        return LlmTokenCallbackHandler(llm_infos={})

    @pytest.fixture
    def handler_with_model_infos(self):
        """Create a handler with predefined model information."""
        llm_infos: Dict[str, float] = {
            "gpt-4": {
                "price_per_1k_input_tokens": 0.01,
                "price_per_1k_output_tokens": 0.03
            },
            "claude-3-sonnet": {
                "price_per_1k_input_tokens": 0.003,
                "price_per_1k_output_tokens": 0.015
            }
        }
        return LlmTokenCallbackHandler(llm_infos=llm_infos)

    def test_calculate_token_costs_from_llm_infos_success(self, handler_with_model_infos):
        """Test successful cost calculation using llm_infos."""
        handler = handler_with_model_infos
        handler.provider_class = "openai"

        cost = handler.calculate_token_costs("gpt-4", 1000, 2000)

        # Expected: (1000/1000 * 0.03) + (2000/1000 * 0.01) = 0.03 + 0.02 = 0.05
        assert cost == 0.05

    def test_calculate_token_costs_from_llm_infos_partial_info(self, handler_with_empty_infos):
        """Test when only partial pricing info is available in llm_infos."""
        handler = handler_with_empty_infos
        handler.llm_infos = {
            "partial-model": {
                "price_per_1k_input_tokens": 0.002
                # Missing price_per_1k_output_tokens
            }
        }
        handler.provider_class = "custom"

        with patch.object(handler, '_get_openai_cost', return_value=None), \
             patch.object(handler, '_get_anthropic_cost', return_value=None):

            cost = handler.calculate_token_costs("partial-model", 1000, 1000)

            # Expected: (1000/1000 * 0.002) + 0.0 = 0.002
            assert cost == 0.002

    def test_calculate_token_costs_openai_fallback(self, handler_with_empty_infos):
        """Test fallback to OpenAI cost calculation."""
        handler = handler_with_empty_infos
        handler.provider_class = "openai"

        with patch.object(handler, '_get_openai_cost', side_effect=[0.025, 0.015]) as mock_openai_cost:
            cost = handler.calculate_token_costs("gpt-3.5-turbo", 1000, 2000)

            # Should call OpenAI cost calculation twice
            assert mock_openai_cost.call_count == 2
            mock_openai_cost.assert_any_call("gpt-3.5-turbo", 1000, token_type=TokenType.COMPLETION)
            mock_openai_cost.assert_any_call("gpt-3.5-turbo", 2000, token_type=TokenType.PROMPT)

            # Expected: 0.025 + 0.015 = 0.04
            assert cost == 0.04

    def test_calculate_token_costs_azure_openai_fallback(self, handler_with_empty_infos):
        """Test fallback to Azure OpenAI cost calculation."""
        handler = handler_with_empty_infos
        handler.provider_class = "azure-openai"

        with patch.object(handler, '_get_openai_cost', side_effect=[0.020, 0.010]) as mock_openai_cost:
            cost = handler.calculate_token_costs("gpt-4", 500, 1500)

            assert mock_openai_cost.call_count == 2
            assert cost == 0.03

    def test_calculate_token_costs_anthropic_fallback(self, handler_with_empty_infos):
        """Test fallback to Anthropic cost calculation."""
        handler = handler_with_empty_infos
        handler.provider_class = "anthropic"

        with patch.object(handler, '_get_anthropic_cost', side_effect=[0.030, 0.006]) as mock_anthropic_cost:
            cost = handler.calculate_token_costs("claude-3-opus", 1000, 2000)

            assert mock_anthropic_cost.call_count == 2
            mock_anthropic_cost.assert_any_call("claude-3-opus", 1000, "completion")
            mock_anthropic_cost.assert_any_call("claude-3-opus", 2000, "prompt")

            assert cost == 0.036

    def test_calculate_token_costs_bedrock_fallback(self, handler_with_empty_infos):
        """Test fallback to Bedrock cost calculation."""
        handler = handler_with_empty_infos
        handler.provider_class = "bedrock"

        with patch.object(handler, '_get_anthropic_cost', side_effect=[0.045, 0.009]) as mock_anthropic_cost:
            cost = handler.calculate_token_costs("anthropic.claude-3-sonnet", 1500, 3000)

            assert mock_anthropic_cost.call_count == 2
            assert cost == 0.054

    def test_calculate_token_costs_no_fallback_available(self, handler_with_empty_infos):
        """Test when no cost information is available anywhere."""
        handler = handler_with_empty_infos
        handler.provider_class = "custom-provider"

        cost = handler.calculate_token_costs("unknown-model", 1000, 2000)

        # Should return 0.0 when no cost information is available
        assert cost == 0.0

    def test_calculate_token_costs_fallback_returns_none(self, handler_with_empty_infos):
        """Test when fallback methods return None."""
        handler = handler_with_empty_infos
        handler.provider_class = "openai"

        with patch.object(handler, '_get_openai_cost', return_value=None):
            cost = handler.calculate_token_costs("unknown-openai-model", 1000, 2000)

            assert cost == 0.0

    def test_calculate_token_costs_mixed_sources(self, handler_with_empty_infos):
        """Test when costs come from different sources (llm_infos and fallback)."""
        handler = handler_with_empty_infos
        handler.llm_infos = {
            "mixed-model": {
                "price_per_1k_input_tokens": 0.005
                # Missing output token pricing
            }
        }
        handler.provider_class = "openai"

        with patch.object(handler, '_get_openai_cost', side_effect=[0.020, None]):
            cost = handler.calculate_token_costs("mixed-model", 1000, 2000)

            # Expected: (1000/1000 * 0.020) + (2000/1000 * 0.005) = 0.020 + 0.010 = 0.030
            assert cost == 0.030

    def test_calculate_token_costs_zero_tokens(self, handler_with_model_infos):
        """Test with zero tokens."""
        handler = handler_with_model_infos
        handler.provider_class = "openai"

        cost = handler.calculate_token_costs("gpt-4", 0, 0)

        assert cost == 0.0

    def test_calculate_token_costs_llm_infos_priority(self, handler_with_model_infos):
        """Test that llm_infos takes priority over fallback methods."""
        handler = handler_with_model_infos
        handler.provider_class = "openai"

        # Mock the fallback to return different values
        with patch.object(handler, '_get_openai_cost', side_effect=[999.0, 999.0]) as mock_openai_cost:
            cost = handler.calculate_token_costs("gpt-4", 1000, 1000)

            # Should not call the fallback since llm_infos has the info
            mock_openai_cost.assert_not_called()

            # Should use llm_infos values: (1000/1000 * 0.03) + (1000/1000 * 0.01) = 0.04
            assert cost == 0.04

    @pytest.mark.parametrize("completion_tokens,prompt_tokens,expected_cost", [
        (100, 200, 0.005),      # Small numbers
        (1000, 2000, 0.05),     # Medium numbers
        (10000, 20000, 0.5),    # Large numbers
        (1, 1, 0.00004),        # Very small numbers
    ])
    def test_calculate_token_costs_various_token_amounts(self, handler_with_model_infos,
                                                         completion_tokens, prompt_tokens, expected_cost):
        """Test cost calculation with various token amounts."""
        handler = handler_with_model_infos
        handler.provider_class = "test"

        cost = handler.calculate_token_costs("gpt-4", completion_tokens, prompt_tokens)

        assert abs(cost - expected_cost) < 0.000001  # Account for floating point precision


class TestEmptyResponseTracking:
    """Test cases for the empty_responses tracking added to LlmTokenCallbackHandler."""

    @pytest.mark.parametrize("message,expected", [
        (AIMessage(content=""), True),
        (AIMessage(content="   "), True),
        (AIMessage(content="here is the answer"), False),
        (AIMessage(content=[]), True),
        (
            AIMessage(
                content="",
                tool_calls=[{"name": "search", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            False,
        ),
    ])
    def test_is_empty_response(self, message, expected):
        """A response is empty only when it carries neither content nor a tool call."""
        assert LlmTokenCallbackHandler._is_empty_response(message) is expected

    def _make_result(self, content, tool_calls=None) -> LLMResult:
        """Build an LLMResult wrapping a single AIMessage with usage metadata."""
        message = AIMessage(
            content=content,
            tool_calls=tool_calls or [],
            usage_metadata={"input_tokens": 10, "output_tokens": 0, "total_tokens": 10},
            response_metadata={"model_name": "gpt-oss:20B"},
        )
        return LLMResult(generations=[[ChatGeneration(message=message)]])

    def _make_handler(self) -> LlmTokenCallbackHandler:
        handler = LlmTokenCallbackHandler(llm_infos={})
        handler.provider_class = "ollama"
        handler.models_token_dict = {"ollama": {}}
        handler.start_time = time()
        return handler

    @pytest.mark.asyncio
    async def test_on_llm_end_counts_empty_response(self):
        """An empty response counts as a successful request AND an empty one."""
        handler = self._make_handler()
        await handler.on_llm_end(self._make_result(content=""))
        assert handler.successful_requests == 1
        assert handler.empty_responses == 1
        assert handler.models_token_dict["ollama"]["gpt-oss:20B"]["empty_responses"] == 1

    @pytest.mark.asyncio
    async def test_on_llm_end_does_not_count_nonempty_response(self):
        """A response with content is a successful request but not an empty one."""
        handler = self._make_handler()
        await handler.on_llm_end(self._make_result(content="a real answer"))
        assert handler.successful_requests == 1
        assert handler.empty_responses == 0
        assert handler.models_token_dict["ollama"]["gpt-oss:20B"]["empty_responses"] == 0
