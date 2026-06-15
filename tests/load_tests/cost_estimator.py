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

"""Estimate USD cost from LLM token counts and model pricing tables.

Uses per-model pricing for known OpenAI models and falls back to a
conservative default for unrecognized model strings.  Pricing is
matched by substring so dated model names (e.g. gpt-5.2-2025-12-11)
resolve to their base model entry.
"""

from tests.load_tests.config import DEFAULT_PRICING
from tests.load_tests.config import MODEL_PRICING
from tests.load_tests.config import TOKENS_PER_MILLION


class CostEstimator:
    """Estimate USD cost from token counts and model pricing."""

    @staticmethod
    def estimate(prompt_tokens, completion_tokens, model="unknown"):
        """Estimate USD cost from token counts and model name.

        Looks up per-model pricing by substring match, then computes
        cost as (tokens / 1M) * rate for prompt and completion
        separately.
        """
        pricing = DEFAULT_PRICING
        for key, val in MODEL_PRICING.items():
            if key in model:
                pricing = val
                break
        prompt_cost = (
            (prompt_tokens / TOKENS_PER_MILLION)
            * pricing.get("prompt", 0)
        )
        completion_cost = (
            (completion_tokens / TOKENS_PER_MILLION)
            * pricing.get("completion", 0)
        )
        return prompt_cost + completion_cost
