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

from threading import Lock
from typing import Any
from typing import Dict
from typing import Optional

from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import LlmTokenCallbackHandler


class CostEstimator:
    """
    Estimates the USD cost of a request from its token counts.

    Prices come from the llm_info the server uses: default_llm_info.hocon, overlaid with
    AGENT_LLM_INFO_FILE when it is set. The server's own LlmTokenCallbackHandler applies them,
    so the estimate matches the server's "Total Cost (USD)". A model with no price in llm_info
    costs 0.0, and the handler logs a WARNING that names the model.
    """

    # Built on the first estimate() call, because loading llm_info parses the whole hocon file.
    # The lock keeps concurrent request threads from loading it more than once.
    price_calculator: Optional[LlmTokenCallbackHandler] = None
    price_calculator_lock: Lock = Lock()

    @staticmethod
    def estimate(prompt_tokens: int, completion_tokens: int, model: str = "unknown") -> float:
        """
        Estimate USD cost from token counts and model name.

        :param prompt_tokens: Prompt tokens used
        :param completion_tokens: Completion tokens used
        :param model: Model name as the server reports it, looked up in llm_info
        :return: Estimated cost in USD; 0.0 when llm_info has no price for the model
        """
        with CostEstimator.price_calculator_lock:
            if CostEstimator.price_calculator is None:
                llm_factory = DefaultLlmFactory()
                llm_factory.load()
                llm_infos: Dict[str, Any] = llm_factory.llm_infos
                CostEstimator.price_calculator = LlmTokenCallbackHandler(llm_infos)
        price_calculator: LlmTokenCallbackHandler = CostEstimator.price_calculator
        cost_dollars: float = price_calculator.calculate_token_costs(model, completion_tokens, prompt_tokens)
        return cost_dollars
