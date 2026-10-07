
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
from typing import List
from unittest import TestCase

from tests.load_tests.reporting.latency_analyzer import LatencyAnalyzer


# These tests read a deliberately-internal helper directly; suppress
# protected-access warnings file-wide.
# pylint: disable=protected-access
class TestLatencyAnalyzer(TestCase):
    """Unit tests for LatencyAnalyzer._percentile()."""

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
