
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
from logging import LogRecord
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase

from tests.load_tests.reporting.latency_analyzer import LatencyAnalyzer


class TestLatencyAnalyzer(TestCase):
    """
    Unit tests for LatencyAnalyzer: percentile(), count_milestones(), and the lines that
    log_latency_analysis() and log_concurrency_timeline() log.
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
        Results with no elapsed time, or 0, are left out of the completion percentiles.
        """
        summary: Dict[str, Any] = {
            "stage": 1,
            "results": [{"elapsed": 3.0}, {"elapsed": 0}, {}, {"elapsed": 1.5}],
        }
        logged_text: str = self._latency_analysis_text(summary)
        self.assertIn("Completion percentiles (Stage 1, 2 requests): p0 1.5s / p50 2.2s / p90 2.9s / p95 2.9s"
                      " / p100 3.0s", logged_text)

    def test_extract_latencies_of_no_results_is_empty(self) -> None:
        """
        A stage with no results has no latencies, so no completion percentiles are logged.
        """
        logged_text: str = self._latency_analysis_text({})
        self.assertNotIn("Completion percentiles", logged_text)

    def test_peak_in_flight_count_is_the_largest_count(self) -> None:
        """
        The peak is the largest in-flight count, wherever it is in the timeline.
        """
        results: List[Dict[str, Any]] = [
            {
                "start_time": 100.0,
                "end_time": 102.0,
            },
            {
                "start_time": 100.5,
                "end_time": 101.0,
            },
            {
                "start_time": 100.5,
                "end_time": 101.0,
            },
            {
                "start_time": 100.5,
                "end_time": 101.5,
            },
        ]
        logged_text: str = self._concurrency_timeline_text(results)
        self.assertIn("Peak in-flight: 4", logged_text)

    def test_build_timeline_puts_an_end_before_a_start_at_the_same_time(self) -> None:
        """
        Times count from the first start, a request with no start time is left out, and an end at the same
        time as a start comes first, so the peak stays 1 over a 2-second chart of 3 buckets.
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
        logged_text: str = self._concurrency_timeline_text(results)
        counts: List[int] = TestLatencyAnalyzer._chart_counts(logged_text)
        self.assertIn("Peak in-flight: 1", logged_text)
        self.assertEqual(counts, [1, 1, 1])

    def test_bucket_peaks_carry_the_count_forward(self) -> None:
        """
        Each bucket starts at the count carried from the bucket before it and keeps its largest count.
        """
        results: List[Dict[str, Any]] = [
            {
                "start_time": 100.0,
                "end_time": 102.5,
            },
            {
                "start_time": 100.0,
                "end_time": 101.2,
            },
        ]
        logged_text: str = self._concurrency_timeline_text(results)
        counts: List[int] = TestLatencyAnalyzer._chart_counts(logged_text)
        self.assertEqual(counts, [2, 2, 1])

    def test_chart_bar_has_one_hash_per_character(self) -> None:
        """
        A bar has one "#" per character: the busiest bucket fills the chart width, and a bucket with
        nothing in flight has none.
        """
        results: List[Dict[str, Any]] = [
            {
                "start_time": 100.0,
                "end_time": 101.0,
            },
            {
                "start_time": 103.0,
                "end_time": 104.0,
            },
        ]
        logged_text: str = self._concurrency_timeline_text(results)
        full_bar: str = ""
        _: int
        # The busiest bucket's bar has one "#" for each character of the chart width.
        for _ in range(LatencyAnalyzer.CHART_WIDTH_CHARACTERS):
            full_bar += "#"
        bars: List[str] = TestLatencyAnalyzer._chart_bars(logged_text)
        self.assertEqual(bars, [full_bar, full_bar, "", full_bar, full_bar])

    def test_count_milestones_lists_each_step_then_the_total(self) -> None:
        """
        Counts go up in steps of COUNT_MILESTONE_STEP and end with the total; none when the total is one step.
        """
        milestones: List[int] = LatencyAnalyzer.count_milestones(120)
        self.assertEqual(milestones, [50, 100, 120])
        no_milestones: List[int] = LatencyAnalyzer.count_milestones(50)
        self.assertEqual(no_milestones, [])

    def _latency_analysis_text(self, summary: Dict[str, Any]) -> str:
        """
        Run log_latency_analysis() on one stage summary.

        :param summary: The stage summary
        :return: The logged lines, joined by newlines
        """
        logged_lines: List[str] = []
        analyzer: LatencyAnalyzer = LatencyAnalyzer([summary])
        with self.assertLogs(LatencyAnalyzer.__module__, level="INFO") as captured:
            analyzer.log_latency_analysis()
        record: LogRecord
        # Collect each logged message.
        for record in captured.records:
            message: str = record.getMessage()
            logged_lines.append(message)
        logged_text: str = "\n".join(logged_lines)
        return logged_text

    def _concurrency_timeline_text(self, results: List[Dict[str, Any]]) -> str:
        """
        Run log_concurrency_timeline() on one stage with the given results.

        :param results: The stage's request results, with "start_time" and "end_time"
        :return: The logged lines, joined by newlines
        """
        logged_lines: List[str] = []
        summary: Dict[str, Any] = {
            "stage": 1,
            "results": results,
        }
        analyzer: LatencyAnalyzer = LatencyAnalyzer([summary])
        with self.assertLogs(LatencyAnalyzer.__module__, level="INFO") as captured:
            analyzer.log_concurrency_timeline()
        record: LogRecord
        # Collect each logged message.
        for record in captured.records:
            message: str = record.getMessage()
            logged_lines.append(message)
        logged_text: str = "\n".join(logged_lines)
        return logged_text

    @staticmethod
    def _chart_counts(logged_text: str) -> List[int]:
        """
        Read the in-flight count at the end of each chart line.

        :param logged_text: Logged lines from log_concurrency_timeline()
        :return: One count per chart bucket, in time order
        """
        counts: List[int] = []
        line: str
        # Chart lines are the ones with a "|" bar.
        for line in logged_text.split("\n"):
            if "|" in line:
                count_text: str = line.rsplit("|", 1)[-1]
                count: int = int(count_text)
                counts.append(count)
        return counts

    @staticmethod
    def _chart_bars(logged_text: str) -> List[str]:
        """
        Read the bar of each chart line, without its padding.

        :param logged_text: Logged lines from log_concurrency_timeline()
        :return: One bar per chart bucket, in time order
        """
        bars: List[str] = []
        line: str
        # Chart lines are the ones with a "|" bar.
        for line in logged_text.split("\n"):
            if "|" in line:
                padded_bar: str = line.split("|")[1]
                trimmed_bar: str = padded_bar.rstrip()
                bars.append(trimmed_bar)
        return bars
