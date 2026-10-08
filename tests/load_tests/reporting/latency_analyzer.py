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

"""Latency analysis — completion timeline, degradation, concurrency
timeline, and server-side timing for diagnosing LLM bottlenecks.
"""

import logging
import math
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple
from typing import Union


from tests.load_tests.config import SEPARATOR_WIDTH
from tests.load_tests.reporting.formatters import Formatters

logger: logging.Logger = logging.getLogger(__name__)

# Completion latency percentiles (percent)
COMPLETION_MILESTONES: List[int] = [0, 50, 90, 95, 100]

# Step size for count-based milestones (e.g. 50, 100, 150...)
COUNT_MILESTONE_STEP: int = 50


class LatencyAnalyzer:
    """Analyse per-request latency data across stages."""

    def __init__(self, stage_summaries: List[Dict[str, Any]]) -> None:
        """
        Constructor.

        :param stage_summaries: Per-stage summaries collected during the run
        """
        self._summaries: List[Dict[str, Any]] = stage_summaries

    @staticmethod
    def _percentile(sorted_values_seconds: List[float], percentage: float) -> float:
        """
        Compute a percentile of pre-sorted values.

        :param sorted_values_seconds: Values sorted in ascending order
        :param percentage: Percentile to compute, 0 to 100
        :return: The interpolated percentile, or 0.0 when there are no values
        """
        if not sorted_values_seconds:
            return 0.0
        index: float = (percentage / 100.0) * (len(sorted_values_seconds) - 1)
        lower_index: int = int(math.floor(index))
        upper_index: int = min(lower_index + 1, len(sorted_values_seconds) - 1)
        fraction: float = index - lower_index
        neighbor_gap_seconds: float = sorted_values_seconds[upper_index] - sorted_values_seconds[lower_index]
        percentile_seconds: float = sorted_values_seconds[lower_index] + fraction * neighbor_gap_seconds
        return percentile_seconds

    # ----------------------------------------------------------
    # 1. Cumulative completion timeline per stage
    # ----------------------------------------------------------

    def log_latency_analysis(self, is_ramp: bool = True) -> None:
        """
        Log completion timeline for each stage.

        :param is_ramp: True to label each stage, False to label each round
        """
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  LATENCY ANALYSIS")
        logger.info("=" * SEPARATOR_WIDTH)

        self._log_completion_timeline(is_ramp=is_ramp)

    def _log_completion_timeline(self, is_ramp: bool) -> None:
        """
        Log completion latency percentiles per stage on one line.

        :param is_ramp: True to label each stage, False to label each round
        """
        for summary in self._summaries:
            latencies_seconds: List[float] = self._extract_latencies(summary)
            if not latencies_seconds:
                continue
            latencies_seconds.sort()
            total: int = len(latencies_seconds)
            stage: Union[int, str] = summary.get("stage", "?")
            round_number: Union[int, str] = summary.get("round", "?")
            label: str = ""
            if is_ramp:
                label = f"Stage {stage}"
                if round_number != "?":
                    label += f", round {round_number}"
            else:
                label = f"Round {round_number}"
            parts_list: List[str] = []
            for percentage in COMPLETION_MILESTONES:
                percentile_seconds: float = self._percentile(latencies_seconds, percentage)
                formatted_duration: str = Formatters.fmt_duration(percentile_seconds, precision=1)
                parts_list.append(f"p{percentage} {formatted_duration}")
            parts: str = " / ".join(parts_list)
            logger.info("\n  Completion percentiles (%s, %s requests): %s", label, total, parts)
            self._log_count_milestones(latencies_seconds)

    @staticmethod
    def _log_count_milestones(sorted_latencies_seconds: List[float]) -> None:
        """
        Log completion times at round-number request counts.

        :param sorted_latencies_seconds: Request latencies in seconds, sorted in ascending order
        """
        total: int = len(sorted_latencies_seconds)
        if total <= COUNT_MILESTONE_STEP:
            return
        milestones: List[int] = list(range(COUNT_MILESTONE_STEP, total, COUNT_MILESTONE_STEP))
        if not milestones or milestones[-1] != total:
            milestones.append(total)
        logger.info("\n  Completion by count:")
        for count in milestones:
            duration_seconds: float = sorted_latencies_seconds[count - 1]
            formatted_duration: str = Formatters.fmt_duration(duration_seconds, precision=1)
            logger.info("    %4d requests completed by %s", count, formatted_duration)

    # ----------------------------------------------------------
    # 2. Round-over-round degradation
    # ----------------------------------------------------------

    def log_degradation(self, is_ramp: bool = True) -> None:  # pylint: disable=unused-argument
        """
        Compare avg latency across rounds/stages at same concurrency.

        :param is_ramp: Not used
        """
        if len(self._summaries) < 2:
            return

        groups: Dict[int, List[Dict[str, Any]]] = self._group_by_concurrency()
        has_degradation: bool = False
        for concurrency, summaries in sorted(groups.items()):
            if len(summaries) < 2:
                continue
            average_latencies_seconds: List[float] = []
            for stage_summary in summaries:
                latencies_seconds: List[float] = self._extract_latencies(stage_summary)
                if latencies_seconds:
                    average_latencies_seconds.append(sum(latencies_seconds) / len(latencies_seconds))
            if len(average_latencies_seconds) < 2:
                continue
            if not has_degradation:
                logger.info("\n  Latency degradation (round-over-round):")
                has_degradation = True
            # One "12.3s" text per round, in round order.
            latency_texts: List[str] = []
            for average_latency_seconds in average_latencies_seconds:
                latency_texts.append(f"{average_latency_seconds:.1f}s")
            parts: str = " -> ".join(latency_texts)
            change_percentage: float = (
                (average_latencies_seconds[-1] - average_latencies_seconds[0]) / average_latencies_seconds[0] * 100
                if average_latencies_seconds[0] > 0 else 0
            )
            sign: str = "+" if change_percentage >= 0 else ""
            logger.info("    %s concurrent: %s (%s%.0f%%)", concurrency, parts, sign, change_percentage)

    # ----------------------------------------------------------
    # 3. Concurrent request timeline
    # ----------------------------------------------------------

    def log_concurrency_timeline(self) -> None:
        """
        Log actual in-flight request counts over time per stage.
        """
        for summary in self._summaries:
            results: List[Dict[str, Any]] = summary.get("results", [])
            timeline: List[Tuple[float, int]] = self._build_timeline(results)
            if not timeline:
                continue
            stage: Union[int, str] = summary.get("stage", "?")
            round_number: Union[int, str] = summary.get("round", "?")
            concurrent: Union[int, str] = summary.get("concurrent", "?")
            peak_in_flight_count: int = LatencyAnalyzer._peak_in_flight_count(timeline)
            logger.info("\n  Concurrency timeline (stage %s, round %s, %s planned):", stage, round_number, concurrent)
            logger.info("    Peak in-flight: %s", peak_in_flight_count)
            self._log_timeline_chart(timeline)

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    @staticmethod
    def _extract_latencies(summary: Dict[str, Any]) -> List[float]:
        """
        Extract elapsed times from stage results.

        :param summary: One stage summary
        :return: Elapsed seconds of each result, leaving out results with no elapsed time
        """
        results: List[Dict[str, Any]] = summary.get("results", [])
        # Keep only the results that have an elapsed time.
        latencies_seconds: List[float] = []
        for result in results:
            elapsed_seconds: float = result.get("elapsed", 0)
            if elapsed_seconds > 0:
                latencies_seconds.append(elapsed_seconds)
        return latencies_seconds

    def _group_by_concurrency(self) -> Dict[int, List[Dict[str, Any]]]:
        """
        Group stage summaries by their concurrency level.

        :return: Concurrency level to the stage summaries run at that level
        """
        groups: Dict[int, List[Dict[str, Any]]] = {}
        for stage_summary in self._summaries:
            concurrency: int = stage_summary.get("concurrent", 0)
            groups.setdefault(concurrency, []).append(stage_summary)
        return groups

    @staticmethod
    def _build_timeline(results: List[Dict[str, Any]]) -> List[Tuple[float, int]]:
        """
        Build a concurrency-over-time timeline from results.

        Returns list of (relative_seconds, in_flight_count) tuples.

        :param results: Request results with start_time and end_time
        :return: (seconds since the first start, requests in flight) after each start and end
        """
        events: List[Tuple[float, int]] = []
        for result in results:
            start_time_seconds: float = result.get("start_time", 0)
            end_time_seconds: float = result.get("end_time", 0)
            if start_time_seconds and end_time_seconds:
                events.append((start_time_seconds, 1))
                events.append((end_time_seconds, -1))
        if not events:
            return []
        events.sort()
        base_time_seconds: float = events[0][0]
        timeline: List[Tuple[float, int]] = []
        in_flight_count: int = 0
        for timestamp_seconds, delta in events:
            in_flight_count += delta
            timeline.append((timestamp_seconds - base_time_seconds, in_flight_count))
        return timeline

    @staticmethod
    def _peak_in_flight_count(timeline: List[Tuple[float, int]]) -> int:
        """
        Return the highest in-flight count in a timeline.

        :param timeline: Non-empty timeline from _build_timeline
        :return: The largest in-flight count
        """
        # Each timeline event is (seconds since start, in-flight count). Keep the largest count seen so far.
        peak_in_flight_count: int = timeline[0][1]
        for event in timeline:
            if event[1] > peak_in_flight_count:
                peak_in_flight_count = event[1]
        return peak_in_flight_count

    @staticmethod
    def _log_timeline_chart(timeline: List[Tuple[float, int]]) -> None:
        """
        Log a simple ASCII chart of concurrency over time.

        :param timeline: Timeline from _build_timeline
        """
        if not timeline:
            return
        maximum_in_flight_count: int = LatencyAnalyzer._peak_in_flight_count(timeline)
        total_duration_seconds: float = timeline[-1][0]
        if total_duration_seconds <= 0 or maximum_in_flight_count <= 0:
            return
        bucket_count: int = min(20, int(total_duration_seconds) + 1)
        bucket_size_seconds: float = total_duration_seconds / bucket_count
        bucket_peaks: List[int] = [0] * bucket_count
        # Carry forward the in-flight count so buckets
        # without events reflect the actual state.
        current_in_flight_count: int = 0
        event_index: int = 0
        for index in range(bucket_count):
            bucket_end_seconds: float = (index + 1) * bucket_size_seconds
            bucket_peaks[index] = current_in_flight_count
            while (event_index < len(timeline)
                   and timeline[event_index][0] < bucket_end_seconds):
                current_in_flight_count = timeline[event_index][1]
                bucket_peaks[index] = max(bucket_peaks[index], current_in_flight_count)
                event_index += 1
        for index, peak_in_flight_count in enumerate(bucket_peaks):
            bucket_start_seconds: float = index * bucket_size_seconds
            bar_length_characters: int = 0
            if maximum_in_flight_count:
                # Bar length scaled so the busiest bucket fills 40 characters; int() drops the fraction.
                bar_length_characters = int(peak_in_flight_count * 40 / maximum_in_flight_count)
            chart: str = "#" * bar_length_characters
            label: str = Formatters.fmt_duration(bucket_start_seconds)
            logger.info("    %8s |%-40s| %d", label, chart, peak_in_flight_count)
