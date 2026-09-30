
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

from typing import Any
from typing import Dict
from uuid import UUID
from uuid import uuid4

import logging

import pytest

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import LLMResult

from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import LlmTokenCallbackHandler
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import PRICE_MODEL_METADATA_KEY
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import PROVIDER_METADATA_KEY

from tests.neuro_san.internals.run_context.langchain.token_counting.owning_agent_scope import owning_agent_scope


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

        cost = handler.calculate_token_costs("partial-model", 1000, 1000)

        # Expected: (1000/1000 * 0.002) + 0.0 = 0.002
        assert cost == 0.002

    def test_calculate_token_costs_no_info_available(self, handler_with_empty_infos, caplog):
        """Test when no cost information is available."""
        handler = handler_with_empty_infos
        handler.provider_class = "custom-provider"

        with caplog.at_level(logging.WARNING):
            cost = handler.calculate_token_costs("unknown-model", 1000, 2000)

        # Should return 0.0 when no cost information is available
        assert cost == 0.0

        # Should log a warning that no price info was found for the model
        assert any(
            record.levelno == logging.WARNING and "No price info found for model unknown-model" in record.getMessage()
            for record in caplog.records
        )

    def test_calculate_token_costs_use_model_name_fallback(self, handler_with_model_infos):
        """Test that an alias entry without prices falls back to its "use_model_name" entry."""
        handler = handler_with_model_infos
        handler.llm_infos["gpt-4-alias"] = {
            "use_model_name": "gpt-4"
        }
        handler.provider_class = "openai"

        cost = handler.calculate_token_costs("gpt-4-alias", 1000, 2000)

        # Expected: same as "gpt-4": (1000/1000 * 0.03) + (2000/1000 * 0.01) = 0.05
        assert cost == 0.05

    def test_calculate_token_costs_use_model_name_missing_target(self, handler_with_empty_infos, caplog):
        """Test that an alias pointing to a nonexistent entry warns and defaults to 0 instead of raising."""
        handler = handler_with_empty_infos
        handler.llm_infos = {
            "dangling-alias": {
                "use_model_name": "no-such-model"
            }
        }
        handler.provider_class = "custom"

        with caplog.at_level(logging.WARNING):
            cost = handler.calculate_token_costs("dangling-alias", 1000, 2000)

        assert cost == 0.0
        assert any(
            record.levelno == logging.WARNING and "No price info found for model dangling-alias" in record.getMessage()
            for record in caplog.records
        )

    def test_calculate_token_costs_zero_tokens(self, handler_with_model_infos):
        """Test with zero tokens."""
        handler = handler_with_model_infos
        handler.provider_class = "openai"

        cost = handler.calculate_token_costs("gpt-4", 0, 0)

        assert cost == 0.0

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

    # ---- Accounting hints in the chat model's metadata ------------------------------------------

    SERIALIZED_CHAT_OPENAI: Dict[str, Any] = {"id": ["langchain", "chat_models", "openai", "ChatOpenAI"]}

    @staticmethod
    def _result_naming(response_model: str) -> LLMResult:
        """
        Build an LLMResult whose response names the given model, with 1000 tokens each way.

        :param response_model: What the provider reported as the model (Azure echoes the deployment)
        :return: The LLMResult on_llm_end() receives
        """
        message: AIMessage = AIMessage(
            content="hello",
            usage_metadata={"input_tokens": 1000, "output_tokens": 1000, "total_tokens": 2000},
            response_metadata={"model_name": response_model},
        )
        return LLMResult(generations=[[ChatGeneration(message=message)]])

    @pytest.mark.asyncio
    async def test_metadata_keys_pick_the_bucket_and_the_price_model(
            self, handler_with_model_infos: LlmTokenCallbackHandler):
        """A policy's metadata books a stock ChatOpenAI under its own bucket, priced by the model it names."""
        run_id: UUID = uuid4()
        with owning_agent_scope(handler_with_model_infos):
            await handler_with_model_infos.on_chat_model_start(
                self.SERIALIZED_CHAT_OPENAI, [], run_id=run_id,
                metadata={PROVIDER_METADATA_KEY: "azure-openai", PRICE_MODEL_METADATA_KEY: "gpt-4"})
            await handler_with_model_infos.on_llm_end(self._result_naming("my-deployment"), run_id=run_id)

        assert "openai" not in handler_with_model_infos.models_token_dict
        entry: Dict[str, Any] = handler_with_model_infos.models_token_dict["azure-openai"]["gpt-4"]
        assert entry["total_tokens"] == 2000
        # 1000 input tokens at 0.01 per 1k plus 1000 output tokens at 0.03 per 1k
        assert entry["total_cost"] == pytest.approx(0.04)
        assert handler_with_model_infos.total_cost == pytest.approx(0.04)
        # The hint is consumed with the run it was recorded for.
        assert not handler_with_model_infos.price_model_names

    @pytest.mark.asyncio
    async def test_without_metadata_the_class_table_and_the_response_model_apply(
            self, handler_with_model_infos: LlmTokenCallbackHandler):
        """Without the keys, the bucket comes from CLASS_TABLE and the response's own model is priced."""
        run_id: UUID = uuid4()
        with owning_agent_scope(handler_with_model_infos):
            await handler_with_model_infos.on_chat_model_start(
                self.SERIALIZED_CHAT_OPENAI, [], run_id=run_id, metadata={})
            await handler_with_model_infos.on_llm_end(self._result_naming("my-deployment"), run_id=run_id)

        entry: Dict[str, Any] = handler_with_model_infos.models_token_dict["openai"]["my-deployment"]
        assert entry["total_tokens"] == 2000
        assert entry["total_cost"] == 0.0

    @pytest.mark.asyncio
    async def test_price_model_also_applies_to_a_downstream_agents_call(
            self, handler_with_model_infos: LlmTokenCallbackHandler):
        """A downstream agent's call is not booked per model here, but its cost joins the totals at the named price."""
        run_id: UUID = uuid4()
        # No owning_agent_scope: the events belong to a downstream agent's chat model.
        await handler_with_model_infos.on_chat_model_start(
            self.SERIALIZED_CHAT_OPENAI, [], run_id=run_id,
            metadata={PROVIDER_METADATA_KEY: "azure-openai", PRICE_MODEL_METADATA_KEY: "gpt-4"})
        await handler_with_model_infos.on_llm_end(self._result_naming("my-deployment"), run_id=run_id)

        assert not handler_with_model_infos.models_token_dict
        assert handler_with_model_infos.total_cost == pytest.approx(0.04)

    @pytest.mark.asyncio
    async def test_failed_run_drops_its_price_model(self, handler_with_model_infos: LlmTokenCallbackHandler):
        """A run that ends in on_llm_error() never reaches on_llm_end(), so its hint is released there instead."""
        run_id: UUID = uuid4()
        with owning_agent_scope(handler_with_model_infos):
            await handler_with_model_infos.on_chat_model_start(
                self.SERIALIZED_CHAT_OPENAI, [], run_id=run_id, metadata={PRICE_MODEL_METADATA_KEY: "gpt-4"})
            await handler_with_model_infos.on_llm_error(RuntimeError("boom"), run_id=run_id)

        assert not handler_with_model_infos.price_model_names
        assert handler_with_model_infos.successful_requests == 0
