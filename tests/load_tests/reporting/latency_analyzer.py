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
import math
from typing import Any
from typing import Dict
from typing import List
from typing import Union


from tests.load_tests.reporting.formatters import Formatters

logger: logging.Logger = logging.getLogger(__name__)

# Completion latency percentiles (percent)
COMPLETION_MILESTONES: List[int] = [0, 50, 90, 95, 100]

# Step size for count-based milestones (e.g. 50, 100, 150...)
COUNT_MILESTONE_STEP: int = 50


class LatencyAnalyzer:
    """
    Analyse per-request latency data across stages: completion timeline,
    round-over-round degradation and concurrency timeline, for diagnosing LLM bottlenecks.
    """

    # Largest number of buckets in the concurrency chart.
    MAXIMUM_CHART_BUCKETS: int = 20

    # Width of the concurrency chart bars, in characters.
    CHART_WIDTH_CHARACTERS: int = 40

    def __init__(self, stage_summaries: List[Dict[str, Any]]) -> None:
        """
        Constructor.

        :param stage_summaries: Per-stage summaries collected during the run
        """
        self._summaries: List[Dict[str, Any]] = stage_summaries

    # ----------------------------------------------------------
    # 1. Cumulative completion timeline per stage
    # ----------------------------------------------------------

    def log_latency_analysis(self, is_ramp: bool = True) -> None:
        """
        Log completion timeline for each stage.

        :param is_ramp: True to label each stage, False to label each round
        """
        logger.info("\n%s", Formatters.SEPARATOR_LINE)
        logger.info("  LATENCY ANALYSIS")
        logger.info("%s", Formatters.SEPARATOR_LINE)

        self._log_completion_timeline(is_ramp=is_ramp)

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
        concurrency_levels: List[int] = sorted(groups)
        concurrency: int
        # One degradation line per concurrency level that ran 2 or more rounds, lowest level first.
        for concurrency in concurrency_levels:
            summaries: List[Dict[str, Any]] = groups.get(concurrency, [])
            if len(summaries) < 2:
                continue
            average_latencies_seconds: List[float] = []
            stage_summary: Dict[str, Any]
            # Average latency of each round that has latency data.
            for stage_summary in summaries:
                latencies_seconds: List[float] = self._extract_latencies(stage_summary)
                if latencies_seconds:
                    average_latencies_seconds.append(sum(latencies_seconds) / len(latencies_seconds))
            if len(average_latencies_seconds) < 2:
                continue
            if not has_degradation:
                logger.info("\n  Latency degradation (round-over-round):")
                has_degradation = True
            latency_texts: List[str] = []
            average_latency_seconds: float
            # One "12.3s" text per round, in round order.
            for average_latency_seconds in average_latencies_seconds:
                latency_texts.append(f"{average_latency_seconds:.1f}s")
            parts: str = " -> ".join(latency_texts)
            change_percentage: float = 0
            if average_latencies_seconds[0] > 0:
                change_percentage = (
                    (average_latencies_seconds[-1] - average_latencies_seconds[0]) / average_latencies_seconds[0] * 100
                )
            sign: str = ""
            if change_percentage >= 0:
                sign = "+"
            logger.info("    %s concurrent: %s (%s%.0f%%)", concurrency, parts, sign, change_percentage)

    # ----------------------------------------------------------
    # 3. Concurrent request timeline
    # ----------------------------------------------------------

    def log_concurrency_timeline(self) -> None:
        """
        Log actual in-flight request counts over time per stage.
        """
        summary: Dict[str, Any]
        # Log the concurrency timeline of each stage that has one.
        for summary in self._summaries:
            results: List[Dict[str, Any]] = summary.get("results", [])
            timeline: List[Dict[str, Union[int, float]]] = self._build_timeline(results)
            if not timeline:
                continue
            stage: Union[int, str] = summary.get("stage", "?")
            round_number: Union[int, str] = summary.get("round", "?")
            concurrent: Union[int, str] = summary.get("concurrent", "?")
            peak_in_flight_count: int = LatencyAnalyzer._peak_in_flight_count(timeline)
            logger.info("\n  Concurrency timeline (stage %s, round %s, %s planned):", stage, round_number, concurrent)
            logger.info("    Peak in-flight: %s", peak_in_flight_count)
            self._log_timeline_chart(timeline)

    @staticmethod
    def count_milestones(total: int) -> List[int]:
        """
        List the round-number request counts that the completion-by-count lines report.

        :param total: Number of requests with a latency
        :return: Each multiple of COUNT_MILESTONE_STEP below total, then total itself; empty when total is
                 COUNT_MILESTONE_STEP or less
        """
        milestones: List[int] = []
        if total <= COUNT_MILESTONE_STEP:
            return milestones
        milestone: int
        # Each multiple of the step below the total, smallest first.
        for milestone in range(COUNT_MILESTONE_STEP, total, COUNT_MILESTONE_STEP):
            milestones.append(milestone)
        # range() stops before total, so total itself comes last.
        milestones.append(total)
        return milestones

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _log_completion_timeline(self, is_ramp: bool) -> None:
        """
        Log completion latency percentiles per stage on one line.

        :param is_ramp: True to label each stage, False to label each round
        """
        summary: Dict[str, Any]
        # Log the completion percentiles of each stage that has latencies.
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
            percentage: int
            # One "p<N> <duration>" part per milestone percentage.
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
        milestones: List[int] = LatencyAnalyzer.count_milestones(total)
        if not milestones:
            return
        logger.info("\n  Completion by count:")
        count: int
        # One log line per count milestone.
        for count in milestones:
            duration_seconds: float = sorted_latencies_seconds[count - 1]
            formatted_duration: str = Formatters.fmt_duration(duration_seconds, precision=1)
            logger.info("    %4d requests completed by %s", count, formatted_duration)

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
        result: Dict[str, Any]
        # Collect the elapsed time of each request that has one.
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
        stage_summary: Dict[str, Any]
        # Group the stage summaries by concurrency.
        for stage_summary in self._summaries:
            concurrency: int = stage_summary.get("concurrent", 0)
            groups.setdefault(concurrency, []).append(stage_summary)
        return groups

    @staticmethod
    def _build_timeline(results: List[Dict[str, Any]]) -> List[Dict[str, Union[int, float]]]:
        """
        Build a concurrency-over-time timeline from results.

        :param results: Request results with start_time and end_time
        :return: One dictionary per request start and end, in time order, with "time_seconds" (seconds since the first
                 start) and "in_flight_count" (requests in flight after that start or end)
        """
        events: List[Dict[str, Union[int, float]]] = LatencyAnalyzer._timeline_events(results)
        if not events:
            return []
        # Order by time, with ends (-1) before starts (+1) at the same time.
        # sort() is stable, so sorting by change first and then by time gives that order.
        events.sort(key=LatencyAnalyzer._event_in_flight_change)
        events.sort(key=LatencyAnalyzer._event_time_seconds)
        first_event: Dict[str, Union[int, float]] = events[0]
        base_time_seconds: float = first_event.get("time_seconds", 0.0)
        timeline: List[Dict[str, Union[int, float]]] = []
        in_flight_count: int = 0
        event: Dict[str, Union[int, float]]
        # Apply each event to the running in-flight count.
        for event in events:
            in_flight_change: int = event.get("in_flight_change", 0)
            in_flight_count += in_flight_change
            event_time_seconds: float = event.get("time_seconds", 0.0)
            relative_time_seconds: float = event_time_seconds - base_time_seconds
            timeline_entry: Dict[str, Union[int, float]] = {
                "time_seconds": relative_time_seconds,
                "in_flight_count": in_flight_count,
            }
            timeline.append(timeline_entry)
        return timeline

    @staticmethod
    def _timeline_events(results: List[Dict[str, Any]]) -> List[Dict[str, Union[int, float]]]:
        """
        Collect a start event and an end event for each request that has both times.

        :param results: Request results with start_time and end_time
        :return: Events from _timeline_event(), in result order: the start, then the end of each request
        """
        events: List[Dict[str, Union[int, float]]] = []
        result: Dict[str, Any]
        # Add a start event (+1) and an end event (-1) for each timed request.
        for result in results:
            start_time_seconds: float = result.get("start_time", 0)
            end_time_seconds: float = result.get("end_time", 0)
            if start_time_seconds and end_time_seconds:
                start_event: Dict[str, Union[int, float]] = LatencyAnalyzer._timeline_event(start_time_seconds, 1)
                events.append(start_event)
                end_event: Dict[str, Union[int, float]] = LatencyAnalyzer._timeline_event(end_time_seconds, -1)
                events.append(end_event)
        return events

    @staticmethod
    def _timeline_event(time_seconds: float, in_flight_change: int) -> Dict[str, Union[int, float]]:
        """
        Build one request start or end event for _build_timeline().

        :param time_seconds: Time of the start or end, in seconds
        :param in_flight_change: 1 for a request start, -1 for a request end
        :return: A dictionary with "time_seconds" and "in_flight_change"
        """
        event: Dict[str, Union[int, float]] = {
            "time_seconds": time_seconds,
            "in_flight_change": in_flight_change,
        }
        return event

    @staticmethod
    def _event_in_flight_change(event: Dict[str, Union[int, float]]) -> int:
        """
        Sort key for _build_timeline() events.

        :param event: One event from _timeline_event()
        :return: The "in_flight_change" of the event
        """
        in_flight_change: int = event.get("in_flight_change", 0)
        return in_flight_change

    @staticmethod
    def _event_time_seconds(event: Dict[str, Union[int, float]]) -> float:
        """
        Sort key for _build_timeline() events.

        :param event: One event from _timeline_event()
        :return: The "time_seconds" of the event
        """
        time_seconds: float = event.get("time_seconds", 0.0)
        return time_seconds

    @staticmethod
    def _peak_in_flight_count(timeline: List[Dict[str, Union[int, float]]]) -> int:
        """
        Return the highest in-flight count in a timeline.

        :param timeline: Non-empty timeline from _build_timeline()
        :return: The largest in-flight count
        """
        first_entry: Dict[str, Union[int, float]] = timeline[0]
        peak_in_flight_count: int = first_entry.get("in_flight_count", 0)
        timeline_entry: Dict[str, Union[int, float]]
        # Keep the largest count seen so far.
        for timeline_entry in timeline:
            in_flight_count: int = timeline_entry.get("in_flight_count", 0)
            peak_in_flight_count = max(peak_in_flight_count, in_flight_count)
        return peak_in_flight_count

    @staticmethod
    def _log_timeline_chart(timeline: List[Dict[str, Union[int, float]]]) -> None:
        """
        Log a simple ASCII chart of concurrency over time.

        :param timeline: Timeline from _build_timeline()
        """
        if not timeline:
            return
        maximum_in_flight_count: int = LatencyAnalyzer._peak_in_flight_count(timeline)
        last_entry: Dict[str, Union[int, float]] = timeline[-1]
        total_duration_seconds: float = last_entry.get("time_seconds", 0.0)
        if total_duration_seconds <= 0 or maximum_in_flight_count <= 0:
            return
        bucket_count: int = min(LatencyAnalyzer.MAXIMUM_CHART_BUCKETS, int(total_duration_seconds) + 1)
        bucket_size_seconds: float = total_duration_seconds / bucket_count
        bucket_peaks: List[int] = LatencyAnalyzer._bucket_peaks(timeline, bucket_count, bucket_size_seconds)
        index: int
        peak_in_flight_count: int
        # One chart line per bucket.
        for index, peak_in_flight_count in enumerate(bucket_peaks):
            bucket_start_seconds: float = index * bucket_size_seconds
            # Bar length scaled so the busiest bucket fills the chart width; int() drops the fraction.
            bar_length_characters: int = int(peak_in_flight_count * LatencyAnalyzer.CHART_WIDTH_CHARACTERS
                                             / maximum_in_flight_count)
            chart: str = LatencyAnalyzer._chart_bar(bar_length_characters)
            label: str = Formatters.fmt_duration(bucket_start_seconds)
            # "%-*s" takes its width from the argument before the bar.
            logger.info("    %8s |%-*s| %d", label, LatencyAnalyzer.CHART_WIDTH_CHARACTERS, chart, peak_in_flight_count)

    @staticmethod
    def _bucket_peaks(timeline: List[Dict[str, Union[int, float]]], bucket_count: int,
                      bucket_size_seconds: float) -> List[int]:
        """
        Find the peak in-flight count in each time bucket of the concurrency chart.

        :param timeline: Non-empty timeline from _build_timeline()
        :param bucket_count: Number of buckets in the chart
        :param bucket_size_seconds: Time span of each bucket, in seconds
        :return: One peak in-flight count per bucket, in time order
        """
        bucket_peaks: List[int] = []
        index: int
        # Start every bucket at 0.
        for index in range(bucket_count):
            bucket_peaks.append(0)
        # Carry forward the in-flight count so buckets
        # without events reflect the actual state.
        current_in_flight_count: int = 0
        event_index: int = 0
        # Fill each bucket with the peak in-flight count during its time span.
        for index in range(bucket_count):
            bucket_end_seconds: float = (index + 1) * bucket_size_seconds
            bucket_peaks[index] = current_in_flight_count
            # Apply the timeline entries that come before the end of this bucket.
            while event_index < len(timeline):
                timeline_entry: Dict[str, Union[int, float]] = timeline[event_index]
                entry_time_seconds: float = timeline_entry.get("time_seconds", 0.0)
                is_in_bucket: bool = entry_time_seconds < bucket_end_seconds
                if not is_in_bucket:
                    break
                current_in_flight_count = timeline_entry.get("in_flight_count", 0)
                bucket_peaks[index] = max(bucket_peaks[index], current_in_flight_count)
                event_index += 1
        return bucket_peaks

    @staticmethod
    def _chart_bar(bar_length_characters: int) -> str:
        """
        Build one bar of the concurrency chart.

        :param bar_length_characters: Length of the bar, in characters
        :return: The bar, one "#" per character; empty when the length is 0 or less
        """
        chart_bar: str = ""
        unused_bar_position: int
        # Add one "#" per character of the bar.
        for unused_bar_position in range(bar_length_characters):
            chart_bar += "#"
        return chart_bar
