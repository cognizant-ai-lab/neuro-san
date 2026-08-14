
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
from unittest import TestCase

from tests.load_tests.config import DEFAULT_PRICING
from tests.load_tests.config import MODEL_PRICING
from tests.load_tests.cost_estimator import CostEstimator


class TestCostEstimator(TestCase):
    """
    Unit tests for CostEstimator.estimate().

    The estimate is what the dry-run probe shows before a paid run, so
    a wrong rate means an under-stated bill at exactly the moment the
    user is deciding whether to spend the money.
    """

    def test_rate_is_per_million_tokens(self):
        """Prompt and completion tokens are billed at their own rates."""
        pricing = MODEL_PRICING["gpt-4o"]
        expected = pricing["prompt"] + pricing["completion"]

        self.assertAlmostEqual(
            CostEstimator.estimate(1_000_000, 1_000_000, "gpt-4o"),
            expected,
        )

    def test_longest_matching_model_key_wins(self):
        """A more specific model must not be priced as its base model.

        'gpt-4o' is a substring of 'gpt-4o-mini', so matching in
        dictionary order would bill mini traffic at ~17x its real
        prompt rate.  Keys are tried longest-first to prevent that.
        """
        mini = CostEstimator.estimate(1_000_000, 0, "gpt-4o-mini")

        self.assertAlmostEqual(mini, MODEL_PRICING["gpt-4o-mini"]["prompt"])
        self.assertLess(mini, CostEstimator.estimate(1_000_000, 0, "gpt-4o"))

    def test_nano_is_not_priced_as_mini(self):
        """The same specificity rule holds across a three-way prefix."""
        nano = CostEstimator.estimate(1_000_000, 0, "gpt-4.1-nano")

        self.assertAlmostEqual(nano, MODEL_PRICING["gpt-4.1-nano"]["prompt"])

    def test_dated_model_names_resolve_to_their_base_model(self):
        """Server-reported names carry a date suffix and still match."""
        dated = CostEstimator.estimate(1_000_000, 0, "gpt-5.2-2025-12-11")

        self.assertAlmostEqual(dated, MODEL_PRICING["gpt-5.2"]["prompt"])

    def test_unknown_model_falls_back_to_default_pricing(self):
        """An unrecognized model is costed, not silently free."""
        unknown = CostEstimator.estimate(1_000_000, 0, "llama-9")

        self.assertAlmostEqual(unknown, DEFAULT_PRICING["prompt"])

    def test_zero_tokens_cost_nothing(self):
        """A request with no token data contributes no cost."""
        self.assertEqual(CostEstimator.estimate(0, 0, "gpt-4o"), 0.0)
