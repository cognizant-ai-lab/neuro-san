
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

import logging

from typing import Any
from typing import Dict
from typing import List
from typing import Tuple
from unittest import IsolatedAsyncioTestCase
from uuid import UUID
from uuid import uuid4

from typing_extensions import override

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import LLMResult

from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import LlmTokenCallbackHandler
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import PRICE_MODEL_METADATA_KEY
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import PROVIDER_METADATA_KEY

from tests.neuro_san.internals.run_context.langchain.token_counting.owning_agent_scope import owning_agent_scope


class TestLlmTokenCallbackHandler(IsolatedAsyncioTestCase):
    """
    Test cases for LlmTokenCallbackHandler: cost calculation from llm_infos, and the accounting hints an
    LlmPolicy can put in a chat model's metadata.
    """

    # What langchain serializes for a stock ChatOpenAI; the last id element is the class name.
    SERIALIZED_CHAT_OPENAI: Dict[str, Any] = {"id": ["langchain", "chat_models", "openai", "ChatOpenAI"]}

    @override
    def setUp(self) -> None:
        """
        Builds one handler without prices and one with prices for gpt-4 and claude-3-sonnet.
        """
        self.empty_handler: LlmTokenCallbackHandler = LlmTokenCallbackHandler(llm_infos={})
        llm_infos: Dict[str, Any] = {
            "gpt-4": {
                "price_per_1k_input_tokens": 0.01,
                "price_per_1k_output_tokens": 0.03
            },
            "claude-3-sonnet": {
                "price_per_1k_input_tokens": 0.003,
                "price_per_1k_output_tokens": 0.015
            }
        }
        self.priced_handler: LlmTokenCallbackHandler = LlmTokenCallbackHandler(llm_infos=llm_infos)

    def test_calculate_token_costs_from_llm_infos_success(self) -> None:
        """
        Cost comes from the llm_infos prices.
        """
        self.priced_handler.provider_class = "openai"

        cost: float = self.priced_handler.calculate_token_costs("gpt-4", 1000, 2000)

        # (1000/1000 * 0.03) + (2000/1000 * 0.01) = 0.03 + 0.02 = 0.05
        self.assertAlmostEqual(cost, 0.05)

    def test_calculate_token_costs_from_llm_infos_partial_info(self) -> None:
        """
        Only the side with a price contributes when llm_infos has partial pricing.
        """
        self.empty_handler.llm_infos = {
            "partial-model": {
                "price_per_1k_input_tokens": 0.002
                # Missing price_per_1k_output_tokens
            }
        }
        self.empty_handler.provider_class = "custom"

        cost: float = self.empty_handler.calculate_token_costs("partial-model", 1000, 1000)

        # (1000/1000 * 0.002) + 0.0 = 0.002
        self.assertAlmostEqual(cost, 0.002)

    def test_calculate_token_costs_no_info_available(self) -> None:
        """
        No price information gives a cost of 0 and a warning naming the model.
        """
        self.empty_handler.provider_class = "custom-provider"

        with self.assertLogs(level=logging.WARNING) as logs:
            cost: float = self.empty_handler.calculate_token_costs("unknown-model", 1000, 2000)

        self.assertEqual(cost, 0.0)
        self._assert_warned(logs.output, "No price info found for model unknown-model")

    def test_calculate_token_costs_use_model_name_fallback(self) -> None:
        """
        An alias entry without prices falls back to its "use_model_name" entry.
        """
        self.priced_handler.llm_infos["gpt-4-alias"] = {
            "use_model_name": "gpt-4"
        }
        self.priced_handler.provider_class = "openai"

        cost: float = self.priced_handler.calculate_token_costs("gpt-4-alias", 1000, 2000)

        # Same as "gpt-4": (1000/1000 * 0.03) + (2000/1000 * 0.01) = 0.05
        self.assertAlmostEqual(cost, 0.05)

    def test_calculate_token_costs_use_model_name_missing_target(self) -> None:
        """
        An alias pointing to a nonexistent entry warns and defaults to 0 instead of raising.
        """
        self.empty_handler.llm_infos = {
            "dangling-alias": {
                "use_model_name": "no-such-model"
            }
        }
        self.empty_handler.provider_class = "custom"

        with self.assertLogs(level=logging.WARNING) as logs:
            cost: float = self.empty_handler.calculate_token_costs("dangling-alias", 1000, 2000)

        self.assertEqual(cost, 0.0)
        self._assert_warned(logs.output, "No price info found for model dangling-alias")

    def test_calculate_token_costs_zero_tokens(self) -> None:
        """
        Zero tokens cost nothing.
        """
        self.priced_handler.provider_class = "openai"

        cost: float = self.priced_handler.calculate_token_costs("gpt-4", 0, 0)

        self.assertEqual(cost, 0.0)

    def test_calculate_token_costs_various_token_amounts(self) -> None:
        """
        Cost scales with the token counts.
        """
        cases: List[Tuple[int, int, float]] = [
            (100, 200, 0.005),      # Small numbers
            (1000, 2000, 0.05),     # Medium numbers
            (10000, 20000, 0.5),    # Large numbers
            (1, 1, 0.00004),        # Very small numbers
        ]
        self.priced_handler.provider_class = "test"
        for completion_tokens, prompt_tokens, expected_cost in cases:
            with self.subTest(completion_tokens=completion_tokens, prompt_tokens=prompt_tokens):
                cost: float = self.priced_handler.calculate_token_costs("gpt-4", completion_tokens, prompt_tokens)

                self.assertAlmostEqual(cost, expected_cost, places=6)

    def _assert_warned(self, output: List[str], text: str) -> None:
        """
        Checks that one of the captured log lines carries the given text.

        :param output: The formatted log lines assertLogs() captured
        :param text: The text one of them must contain
        """
        found: bool = False
        for line in output:
            if text in line:
                found = True
        self.assertTrue(found, f"no log line contains {text!r}: {output}")

    # ---- Accounting hints in the chat model's metadata ------------------------------------------

    @staticmethod
    def _result_naming(response_model: str) -> LLMResult:
        """
        Builds an LLMResult whose response names the given model, with 1000 tokens each way.

        :param response_model: What the provider reported as the model (Azure echoes the deployment)
        :return: The LLMResult on_llm_end() receives
        """
        message: AIMessage = AIMessage(
            content="hello",
            usage_metadata={"input_tokens": 1000, "output_tokens": 1000, "total_tokens": 2000},
            response_metadata={"model_name": response_model},
        )
        return LLMResult(generations=[[ChatGeneration(message=message)]])

    async def test_metadata_keys_pick_the_bucket_and_the_price_model(self) -> None:
        """
        A policy's metadata books a stock ChatOpenAI under its own bucket, priced by the model it names.
        """
        run_id: UUID = uuid4()
        with owning_agent_scope(self.priced_handler):
            await self.priced_handler.on_chat_model_start(
                self.SERIALIZED_CHAT_OPENAI, [], run_id=run_id,
                metadata={PROVIDER_METADATA_KEY: "azure-openai", PRICE_MODEL_METADATA_KEY: "gpt-4"})
            await self.priced_handler.on_llm_end(self._result_naming("my-deployment"), run_id=run_id)

        self.assertNotIn("openai", self.priced_handler.models_token_dict)
        entry: Dict[str, Any] = self.priced_handler.models_token_dict.get("azure-openai", {}).get("gpt-4", {})
        self.assertEqual(entry.get("total_tokens"), 2000)
        # 1000 input tokens at 0.01 per 1k plus 1000 output tokens at 0.03 per 1k
        self.assertAlmostEqual(entry.get("total_cost"), 0.04)
        self.assertAlmostEqual(self.priced_handler.total_cost, 0.04)
        # The hint is consumed with the run it was recorded for.
        self.assertEqual(self.priced_handler.price_model_names, {})

    async def test_without_metadata_the_class_table_and_the_response_model_apply(self) -> None:
        """
        Without the keys, the bucket comes from CLASS_TABLE and the response's own model is priced.
        """
        run_id: UUID = uuid4()
        with owning_agent_scope(self.priced_handler):
            await self.priced_handler.on_chat_model_start(
                self.SERIALIZED_CHAT_OPENAI, [], run_id=run_id, metadata={})
            await self.priced_handler.on_llm_end(self._result_naming("my-deployment"), run_id=run_id)

        entry: Dict[str, Any] = self.priced_handler.models_token_dict.get("openai", {}).get("my-deployment", {})
        self.assertEqual(entry.get("total_tokens"), 2000)
        self.assertEqual(entry.get("total_cost"), 0.0)

    async def test_price_model_also_applies_to_a_downstream_agents_call(self) -> None:
        """
        A downstream agent's call is not booked per model here, but its cost joins the totals at the named price.
        """
        run_id: UUID = uuid4()
        # No owning_agent_scope: the events belong to a downstream agent's chat model.
        await self.priced_handler.on_chat_model_start(
            self.SERIALIZED_CHAT_OPENAI, [], run_id=run_id,
            metadata={PROVIDER_METADATA_KEY: "azure-openai", PRICE_MODEL_METADATA_KEY: "gpt-4"})
        await self.priced_handler.on_llm_end(self._result_naming("my-deployment"), run_id=run_id)

        self.assertEqual(self.priced_handler.models_token_dict, {})
        self.assertAlmostEqual(self.priced_handler.total_cost, 0.04)

    async def test_failed_run_drops_its_price_model(self) -> None:
        """
        A run that ends in on_llm_error() never reaches on_llm_end(), so its hint is released there instead.
        """
        run_id: UUID = uuid4()
        with owning_agent_scope(self.priced_handler):
            await self.priced_handler.on_chat_model_start(
                self.SERIALIZED_CHAT_OPENAI, [], run_id=run_id, metadata={PRICE_MODEL_METADATA_KEY: "gpt-4"})
            await self.priced_handler.on_llm_error(RuntimeError("boom"), run_id=run_id)

        self.assertEqual(self.priced_handler.price_model_names, {})
        self.assertEqual(self.priced_handler.successful_requests, 0)
