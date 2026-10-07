
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
from typing import List
from typing import Tuple
from unittest import TestCase

from tests.load_tests.reporting.latency_analyzer import LatencyAnalyzer


# These tests read a deliberately-internal helper directly; suppress
# protected-access warnings file-wide.
# pylint: disable=protected-access
class TestLatencyAnalyzer(TestCase):
    """Unit tests for LatencyAnalyzer helpers: _percentile(), _extract_latencies() and _peak_in_flight_count()."""

    def test_percentile_of_no_values_is_zero(self) -> None:
        """An empty list has no percentile, so the result is 0.0."""
        self.assertEqual(LatencyAnalyzer._percentile([], 50), 0.0)

    def test_percentile_of_one_value_is_that_value(self) -> None:
        """With one value, every percentile is that value."""
        self.assertEqual(LatencyAnalyzer._percentile([4.0], 0), 4.0)
        self.assertEqual(LatencyAnalyzer._percentile([4.0], 90), 4.0)
        self.assertEqual(LatencyAnalyzer._percentile([4.0], 100), 4.0)

    def test_percentile_ends_are_minimum_and_maximum(self) -> None:
        """The 0th percentile is the smallest value and the 100th the largest."""
        values_seconds: List[float] = [1.0, 2.0, 5.0, 9.0]
        self.assertEqual(LatencyAnalyzer._percentile(values_seconds, 0), 1.0)
        self.assertEqual(LatencyAnalyzer._percentile(values_seconds, 100), 9.0)

    def test_percentile_on_a_value_returns_that_value(self) -> None:
        """The median of an odd-length list is its middle value."""
        self.assertEqual(LatencyAnalyzer._percentile([1.0, 3.0, 8.0], 50), 3.0)

    def test_percentile_between_values_is_interpolated(self) -> None:
        """A percentile between two values lies on the straight line between them."""
        self.assertEqual(LatencyAnalyzer._percentile([1.0, 2.0, 3.0, 4.0], 50), 2.5)
        self.assertAlmostEqual(LatencyAnalyzer._percentile([10.0, 20.0], 90), 19.0)

    def test_extract_latencies_skips_results_without_elapsed_time(self) -> None:
        """Results with no elapsed time, or 0, are left out; the others keep their order."""
        summary: Dict[str, Any] = {"results": [{"elapsed": 3.0}, {"elapsed": 0}, {}, {"elapsed": 1.5}]}
        self.assertEqual(LatencyAnalyzer._extract_latencies(summary), [3.0, 1.5])

    def test_extract_latencies_of_no_results_is_empty(self) -> None:
        """A stage with no results has no latencies."""
        self.assertEqual(LatencyAnalyzer._extract_latencies({}), [])

    def test_peak_in_flight_count_is_the_largest_count(self) -> None:
        """The peak is the largest in-flight count, wherever it is in the timeline."""
        timeline: List[Tuple[float, int]] = [(0.0, 1), (0.5, 4), (1.0, 2)]
        self.assertEqual(LatencyAnalyzer._peak_in_flight_count(timeline), 4)
