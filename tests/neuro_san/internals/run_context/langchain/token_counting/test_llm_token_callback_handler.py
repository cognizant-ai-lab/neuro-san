
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from unittest.mock import patch
from typing import Dict

from langchain_community.callbacks.openai_info import TokenType
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
