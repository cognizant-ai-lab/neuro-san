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

logger = logging.getLogger(__name__)

# Completion latency percentiles (percent)
COMPLETION_MILESTONES = [0, 50, 90, 95, 100]

# Step size for count-based milestones (e.g. 50, 100, 150...)
COUNT_MILESTONE_STEP = 50


class LatencyAnalyzer:
    """Analyse per-request latency data across stages."""

    def __init__(self, stage_summaries: List[Dict[str, Any]]) -> None:
        """
        Constructor.

        :param stage_summaries: Per-stage summaries collected during the run
        """
        self._summaries = stage_summaries

    @staticmethod
    def _percentile(sorted_values: List[float], pct: float) -> float:
        """
        Compute the pct-th percentile from pre-sorted values.

        :param sorted_values: Values sorted in ascending order
        :param pct: Percentile to compute, 0 to 100
        :return: The interpolated percentile, or 0.0 when there are no values
        """
        if not sorted_values:
            return 0.0
        idx: float = (pct / 100.0) * (len(sorted_values) - 1)
        lower: int = int(math.floor(idx))
        upper: int = min(lower + 1, len(sorted_values) - 1)
        frac: float = idx - lower
        return sorted_values[lower] + frac * (
            sorted_values[upper] - sorted_values[lower]
        )

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
            latencies: List[float] = self._extract_latencies(summary)
            if not latencies:
                continue
            latencies.sort()
            total: int = len(latencies)
            stage: Union[int, str] = summary.get("stage", "?")
            rnd: Union[int, str] = summary.get("round", "?")
            label: str = ""
            if is_ramp:
                label = f"Stage {stage}"
                if rnd != "?":
                    label += f", round {rnd}"
            else:
                label = f"Round {rnd}"
            parts_list: List[str] = []
            for pct in COMPLETION_MILESTONES:
                dur: str = Formatters.fmt_duration(
                    self._percentile(latencies, pct),
                    precision=1,
                )
                parts_list.append(f"p{pct} {dur}")
            parts: str = " / ".join(parts_list)
            logger.info(
                "\n  Completion percentiles "
                "(%s, %s requests): %s",
                label, total, parts,
            )
            self._log_count_milestones(latencies)

    @staticmethod
    def _log_count_milestones(sorted_latencies: List[float]) -> None:
        """
        Log completion times at round-number request counts.

        :param sorted_latencies: Request latencies in seconds, sorted in ascending order
        """
        total: int = len(sorted_latencies)
        if total <= COUNT_MILESTONE_STEP:
            return
        milestones: List[int] = list(
            range(
                COUNT_MILESTONE_STEP, total,
                COUNT_MILESTONE_STEP,
            ),
        )
        if not milestones or milestones[-1] != total:
            milestones.append(total)
        logger.info("\n  Completion by count:")
        for count in milestones:
            duration: float = sorted_latencies[count - 1]
            logger.info(
                "    %4d requests completed by %s",
                count,
                Formatters.fmt_duration(duration, precision=1),
            )

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
            avgs: List[float] = []
            for s in summaries:
                latencies: List[float] = self._extract_latencies(s)
                if latencies:
                    avgs.append(
                        sum(latencies) / len(latencies),
                    )
            if len(avgs) < 2:
                continue
            if not has_degradation:
                logger.info(
                    "\n  Latency degradation "
                    "(round-over-round):",
                )
                has_degradation = True
            parts: str = " -> ".join(
                f"{a:.1f}s" for a in avgs
            )
            change: float = (
                (avgs[-1] - avgs[0]) / avgs[0] * 100
                if avgs[0] > 0 else 0
            )
            sign: str = "+" if change >= 0 else ""
            logger.info(
                "    %s concurrent: %s (%s%.0f%%)",
                concurrency, parts, sign, change,
            )

    # ----------------------------------------------------------
    # 3. Concurrent request timeline
    # ----------------------------------------------------------

    def log_concurrency_timeline(self) -> None:
        """Log actual in-flight request counts over time per stage."""
        for summary in self._summaries:
            results: List[Dict[str, Any]] = summary.get("results", [])
            timeline: List[Tuple[float, int]] = self._build_timeline(results)
            if not timeline:
                continue
            stage: Union[int, str] = summary.get("stage", "?")
            rnd: Union[int, str] = summary.get("round", "?")
            concurrent: Union[int, str] = summary.get("concurrent", "?")
            peak: int = max(c for _, c in timeline)
            logger.info(
                "\n  Concurrency timeline "
                "(stage %s, round %s, %s planned):",
                stage, rnd, concurrent,
            )
            logger.info(
                "    Peak in-flight: %s", peak,
            )
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
        return [
            r.get("elapsed", 0)
            for r in results
            if r.get("elapsed", 0) > 0
        ]

    def _group_by_concurrency(self) -> Dict[int, List[Dict[str, Any]]]:
        """
        Group stage summaries by their concurrency level.

        :return: Concurrency level to the stage summaries run at that level
        """
        groups: Dict[int, List[Dict[str, Any]]] = {}
        for s in self._summaries:
            conc: int = s.get("concurrent", 0)
            groups.setdefault(conc, []).append(s)
        return groups

    @staticmethod
    def _build_timeline(results: List[Dict[str, Any]]) -> List[Tuple[float, int]]:
        """Build a concurrency-over-time timeline from results.

        Returns list of (relative_seconds, in_flight_count) tuples.

        :param results: Request results with start_time and end_time
        :return: (seconds since the first start, requests in flight) after each start and end
        """
        events: List[Tuple[float, int]] = []
        for r in results:
            start_t: float = r.get("start_time", 0)
            end_t: float = r.get("end_time", 0)
            if start_t and end_t:
                events.append((start_t, 1))
                events.append((end_t, -1))
        if not events:
            return []
        events.sort()
        base: float = events[0][0]
        timeline: List[Tuple[float, int]] = []
        in_flight: int = 0
        for ts, delta in events:
            in_flight += delta
            timeline.append((ts - base, in_flight))
        return timeline

    @staticmethod
    def _log_timeline_chart(timeline: List[Tuple[float, int]]) -> None:
        """
        Log a simple ASCII chart of concurrency over time.

        :param timeline: Timeline from _build_timeline
        """
        if not timeline:
            return
        max_conc: int = max(c for _, c in timeline)
        total_duration: float = timeline[-1][0]
        if total_duration <= 0 or max_conc <= 0:
            return
        num_buckets: int = min(20, int(total_duration) + 1)
        bucket_size: float = total_duration / num_buckets
        bucket_peaks: List[int] = [0] * num_buckets
        # Carry forward the in-flight count so buckets
        # without events reflect the actual state.
        current: int = 0
        event_idx: int = 0
        for i in range(num_buckets):
            bucket_end: float = (i + 1) * bucket_size
            bucket_peaks[i] = current
            while (event_idx < len(timeline)
                   and timeline[event_idx][0] < bucket_end):
                current = timeline[event_idx][1]
                bucket_peaks[i] = max(
                    bucket_peaks[i], current,
                )
                event_idx += 1
        for i, peak in enumerate(bucket_peaks):
            t_start: float = i * bucket_size
            chart: str = "#" * (peak * 40 // max_conc) if max_conc else ""
            label: str = Formatters.fmt_duration(t_start)
            logger.info(
                "    %8s |%-40s| %d",
                label, chart, peak,
            )
