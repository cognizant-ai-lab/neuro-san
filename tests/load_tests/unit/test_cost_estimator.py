
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
from unittest import TestCase

from typing_extensions import override

from neuro_san.internals.run_context.langchain.llms.llm_info_restorer import LlmInfoRestorer
from tests.load_tests.cost_estimator import CostEstimator


class TestCostEstimator(TestCase):
    """
    Unit tests for CostEstimator.estimate().

    The estimate is what the dry-run probe shows before a paid run, so
    a wrong rate means an under-stated bill at exactly the moment the
    user is deciding whether to spend the money.  The expected prices
    are read from default_llm_info.hocon, the file the server prices with.
    """

    DATED_MODEL: str = "gpt-5.2-2025-12-11"
    ALIAS_MODEL: str = "gpt-5.2"
    UNKNOWN_MODEL: str = "llama-9"
    TOKENS_PER_THOUSAND: int = 1_000

    @override
    def setUp(self) -> None:
        """
        Read the dated model's llm_info entry from the default hocon.
        """
        restorer = LlmInfoRestorer()
        llm_infos: Dict[str, Any] = restorer.restore()
        self.dated_entry: Dict[str, Any] = llm_infos.get(self.DATED_MODEL, {})

    def test_prompt_tokens_use_the_input_price(self) -> None:
        """
        1k prompt tokens cost the model's price_per_1k_input_tokens.
        """
        input_dollars_per_1k_tokens: float = self.dated_entry.get("price_per_1k_input_tokens", 0.0)
        prompt_cost_dollars: float = CostEstimator.estimate(self.TOKENS_PER_THOUSAND, 0, self.DATED_MODEL)

        self.assertGreater(input_dollars_per_1k_tokens, 0.0)
        self.assertAlmostEqual(prompt_cost_dollars, input_dollars_per_1k_tokens)

    def test_completion_tokens_use_the_output_price(self) -> None:
        """
        1k completion tokens cost the model's price_per_1k_output_tokens.
        """
        output_dollars_per_1k_tokens: float = self.dated_entry.get("price_per_1k_output_tokens", 0.0)
        completion_cost_dollars: float = CostEstimator.estimate(0, self.TOKENS_PER_THOUSAND, self.DATED_MODEL)

        self.assertGreater(output_dollars_per_1k_tokens, 0.0)
        self.assertAlmostEqual(completion_cost_dollars, output_dollars_per_1k_tokens)

    def test_alias_is_priced_as_the_model_it_names(self) -> None:
        """
        An alias entry has no price of its own and uses its use_model_name entry's price.
        """
        dated_cost_dollars: float = CostEstimator.estimate(self.TOKENS_PER_THOUSAND, 0, self.DATED_MODEL)
        alias_cost_dollars: float = CostEstimator.estimate(self.TOKENS_PER_THOUSAND, 0, self.ALIAS_MODEL)

        self.assertGreater(dated_cost_dollars, 0.0)
        self.assertAlmostEqual(alias_cost_dollars, dated_cost_dollars)

    def test_unknown_model_costs_nothing_and_logs_a_warning(self) -> None:
        """
        A model missing from llm_info costs 0.0, and a WARNING names the model.
        """
        with self.assertLogs(level="WARNING") as captured_logs:
            unknown_cost_dollars: float = CostEstimator.estimate(self.TOKENS_PER_THOUSAND, 0, self.UNKNOWN_MODEL)
        logged_text: str = "\n".join(captured_logs.output)

        self.assertEqual(unknown_cost_dollars, 0.0)
        self.assertIn(self.UNKNOWN_MODEL, logged_text)

    def test_zero_tokens_cost_nothing(self) -> None:
        """
        A request with no token data contributes no cost.
        """
        self.assertEqual(CostEstimator.estimate(0, 0, self.DATED_MODEL), 0.0)
