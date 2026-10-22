
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
from typing import Union
from unittest import TestCase

from tests.load_tests.reporting.latency_analyzer import LatencyAnalyzer


# These tests read a deliberately-internal helper directly; suppress
# protected-access warnings file-wide.
# pylint: disable=protected-access
class TestLatencyAnalyzer(TestCase):
    """
    Unit tests for LatencyAnalyzer helpers: percentile(), _extract_latencies(), _peak_in_flight_count(),
    _build_timeline(), _bucket_peaks(), _chart_bar() and count_milestones().
    """

    def test_percentile_of_no_values_is_zero(self) -> None:
        """
        An empty list has no percentile, so the result is 0.0.
        """
        percentile_seconds: float = LatencyAnalyzer.percentile([], 50)
        self.assertEqual(percentile_seconds, 0.0)

    def test_percentile_of_one_value_is_that_value(self) -> None:
        """
        With one value, every percentile is that value.
        """
        percentage: float
        # Every percentile of a one-value list is that value.
        for percentage in [0, 90, 100]:
            percentile_seconds: float = LatencyAnalyzer.percentile([4.0], percentage)
            self.assertEqual(percentile_seconds, 4.0)

    def test_percentile_ends_are_minimum_and_maximum(self) -> None:
        """
        The 0th percentile is the smallest value and the 100th the largest.
        """
        values_seconds: List[float] = [1.0, 2.0, 5.0, 9.0]
        minimum_seconds: float = LatencyAnalyzer.percentile(values_seconds, 0)
        maximum_seconds: float = LatencyAnalyzer.percentile(values_seconds, 100)
        self.assertEqual(minimum_seconds, 1.0)
        self.assertEqual(maximum_seconds, 9.0)

    def test_percentile_on_a_value_returns_that_value(self) -> None:
        """
        The median of an odd-length list is its middle value.
        """
        median_seconds: float = LatencyAnalyzer.percentile([1.0, 3.0, 8.0], 50)
        self.assertEqual(median_seconds, 3.0)

    def test_percentile_between_values_is_interpolated(self) -> None:
        """
        A percentile between two values lies on the straight line between them.
        """
        median_seconds: float = LatencyAnalyzer.percentile([1.0, 2.0, 3.0, 4.0], 50)
        ninetieth_seconds: float = LatencyAnalyzer.percentile([10.0, 20.0], 90)
        self.assertEqual(median_seconds, 2.5)
        self.assertAlmostEqual(ninetieth_seconds, 19.0)

    def test_extract_latencies_skips_results_without_elapsed_time(self) -> None:
        """
        Results with no elapsed time, or 0, are left out; the others keep their order.
        """
        summary: Dict[str, Any] = {"results": [{"elapsed": 3.0}, {"elapsed": 0}, {}, {"elapsed": 1.5}]}
        self.assertEqual(LatencyAnalyzer._extract_latencies(summary), [3.0, 1.5])

    def test_extract_latencies_of_no_results_is_empty(self) -> None:
        """
        A stage with no results has no latencies.
        """
        self.assertEqual(LatencyAnalyzer._extract_latencies({}), [])

    def test_peak_in_flight_count_is_the_largest_count(self) -> None:
        """
        The peak is the largest in-flight count, wherever it is in the timeline.
        """
        timeline: List[Dict[str, Union[int, float]]] = [
            {
                "time_seconds": 0.0,
                "in_flight_count": 1,
            },
            {
                "time_seconds": 0.5,
                "in_flight_count": 4,
            },
            {
                "time_seconds": 1.0,
                "in_flight_count": 2,
            },
        ]
        self.assertEqual(LatencyAnalyzer._peak_in_flight_count(timeline), 4)

    def test_build_timeline_puts_an_end_before_a_start_at_the_same_time(self) -> None:
        """
        Times count from the first start, a request with no start time is left out, and an end at the same
        time as a start comes first.
        """
        results: List[Dict[str, Any]] = [
            {
                "start_time": 101.0,
                "end_time": 102.0,
            },
            {
                "start_time": 100.0,
                "end_time": 101.0,
            },
            {
                "start_time": 0,
                "end_time": 103.0,
            },
        ]
        timeline: List[Dict[str, Union[int, float]]] = LatencyAnalyzer._build_timeline(results)
        expected_timeline: List[Dict[str, Union[int, float]]] = [
            {
                "time_seconds": 0.0,
                "in_flight_count": 1,
            },
            {
                "time_seconds": 1.0,
                "in_flight_count": 0,
            },
            {
                "time_seconds": 1.0,
                "in_flight_count": 1,
            },
            {
                "time_seconds": 2.0,
                "in_flight_count": 0,
            },
        ]
        self.assertEqual(timeline, expected_timeline)

    def test_bucket_peaks_carry_the_count_forward(self) -> None:
        """
        Each bucket starts at the count carried from the bucket before it and keeps its largest count.
        """
        timeline: List[Dict[str, Union[int, float]]] = [
            {
                "time_seconds": 0.0,
                "in_flight_count": 2,
            },
            {
                "time_seconds": 1.2,
                "in_flight_count": 1,
            },
            {
                "time_seconds": 2.5,
                "in_flight_count": 0,
            },
        ]
        bucket_peaks: List[int] = LatencyAnalyzer._bucket_peaks(timeline, 3, 1.0)
        self.assertEqual(bucket_peaks, [2, 2, 1])

    def test_chart_bar_has_one_hash_per_character(self) -> None:
        """
        The bar has one "#" per character, and none for a length of 0.
        """
        three_character_bar: str = LatencyAnalyzer._chart_bar(3)
        self.assertEqual(three_character_bar, "###")
        empty_bar: str = LatencyAnalyzer._chart_bar(0)
        self.assertEqual(empty_bar, "")

    def test_count_milestones_lists_each_step_then_the_total(self) -> None:
        """
        Counts go up in steps of COUNT_MILESTONE_STEP and end with the total; none when the total is one step.
        """
        milestones: List[int] = LatencyAnalyzer.count_milestones(120)
        self.assertEqual(milestones, [50, 100, 120])
        no_milestones: List[int] = LatencyAnalyzer.count_milestones(50)
        self.assertEqual(no_milestones, [])
