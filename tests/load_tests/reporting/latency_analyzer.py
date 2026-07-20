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

"""Latency analysis — completion timeline, degradation, concurrency
timeline, and server-side timing for diagnosing LLM bottlenecks.
"""

import logging
import math
from typing import Dict
from typing import List
from typing import Tuple

from tests.load_tests.config import Formatters

from tests.load_tests.config import SEPARATOR_WIDTH

logger = logging.getLogger(__name__)

# Cumulative completion milestones (percent)
COMPLETION_MILESTONES = [50, 60, 70, 80, 90, 95, 100]

# Step size for count-based milestones (e.g. 50, 100, 150...)
COUNT_MILESTONE_STEP = 50


class LatencyAnalyzer:
    """Analyse per-request latency data across stages."""

    def __init__(self, stage_summaries) -> None:
        self._summaries = stage_summaries

    @staticmethod
    def _percentile(sorted_values, pct):
        """Compute the pct-th percentile from pre-sorted values."""
        if not sorted_values:
            return 0.0
        idx = (pct / 100.0) * (len(sorted_values) - 1)
        lower = int(math.floor(idx))
        upper = min(lower + 1, len(sorted_values) - 1)
        frac = idx - lower
        return sorted_values[lower] + frac * (
            sorted_values[upper] - sorted_values[lower]
        )

    # ----------------------------------------------------------
    # 1. Cumulative completion timeline per stage
    # ----------------------------------------------------------

    def log_latency_analysis(self, *, is_ramp=True) -> None:
        """Log completion timeline for each stage."""
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  LATENCY ANALYSIS")
        logger.info("=" * SEPARATOR_WIDTH)

        self._log_completion_timeline(is_ramp=is_ramp)

    def _log_completion_timeline(self, *, is_ramp) -> None:
        """Log cumulative request completion milestones per stage."""
        for summary in self._summaries:
            latencies = self._extract_latencies(summary)
            if not latencies:
                continue
            latencies.sort()
            total = len(latencies)
            stage = summary.get("stage", "?")
            rnd = summary.get("round", "?")
            if is_ramp:
                label = f"Stage {stage}"
                if rnd != "?":
                    label += f", round {rnd}"
            else:
                label = f"Round {rnd}"
            logger.info(
                "\n  Request completion timeline "
                "(%s, %s requests):",
                label, total,
            )
            prev_count = 0
            for pct in COMPLETION_MILESTONES:
                count = int(
                    math.ceil(pct / 100.0 * total),
                )
                if count == prev_count:
                    continue
                prev_count = count
                duration = self._percentile(latencies, pct)
                logger.info(
                    "    %3d%% (%d requests) completed by %s",
                    pct, count,
                    Formatters.fmt_duration(duration, precision=1),
                )
            self._log_count_milestones(latencies)

    @staticmethod
    def _log_count_milestones(sorted_latencies) -> None:
        """Log completion times at round-number request counts."""
        total = len(sorted_latencies)
        if total <= COUNT_MILESTONE_STEP:
            return
        milestones = list(
            range(
                COUNT_MILESTONE_STEP, total,
                COUNT_MILESTONE_STEP,
            ),
        )
        if not milestones or milestones[-1] != total:
            milestones.append(total)
        logger.info("\n  Completion by count:")
        for count in milestones:
            duration = sorted_latencies[count - 1]
            logger.info(
                "    %4d requests completed by %s",
                count,
                Formatters.fmt_duration(duration, precision=1),
            )

    # ----------------------------------------------------------
    # 2. Round-over-round degradation
    # ----------------------------------------------------------

    def log_degradation(  # pylint: disable=unused-argument
            self, *, is_ramp=True,
    ) -> None:
        """Compare avg latency across rounds/stages at same concurrency."""
        if len(self._summaries) < 2:
            return

        groups = self._group_by_concurrency()
        has_degradation = False
        for concurrency, summaries in sorted(groups.items()):
            if len(summaries) < 2:
                continue
            avgs = []
            for s in summaries:
                latencies = self._extract_latencies(s)
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
            parts = " -> ".join(
                f"{a:.1f}s" for a in avgs
            )
            change = (
                (avgs[-1] - avgs[0]) / avgs[0] * 100
                if avgs[0] > 0 else 0
            )
            sign = "+" if change >= 0 else ""
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
            results = summary.get("results", [])
            timeline = self._build_timeline(results)
            if not timeline:
                continue
            stage = summary.get("stage", "?")
            rnd = summary.get("round", "?")
            concurrent = summary.get("concurrent", "?")
            peak = max(c for _, c in timeline)
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
    def _extract_latencies(
            summary,
    ) -> List[float]:
        """Extract elapsed times from stage results."""
        results = summary.get("results", [])
        return [
            r.get("elapsed", 0)
            for r in results
            if r.get("elapsed", 0) > 0
        ]

    def _group_by_concurrency(
            self,
    ) -> Dict[int, list]:
        """Group stage summaries by their concurrency level."""
        groups: Dict[int, list] = {}
        for s in self._summaries:
            conc = s.get("concurrent", 0)
            groups.setdefault(conc, []).append(s)
        return groups

    @staticmethod
    def _build_timeline(
            results,
    ) -> List[Tuple[float, int]]:
        """Build a concurrency-over-time timeline from results.

        Returns list of (relative_seconds, in_flight_count) tuples.
        """
        events: List[Tuple[float, int]] = []
        for r in results:
            start_t = r.get("start_time", 0)
            end_t = r.get("end_time", 0)
            if start_t and end_t:
                events.append((start_t, 1))
                events.append((end_t, -1))
        if not events:
            return []
        events.sort()
        base = events[0][0]
        timeline: List[Tuple[float, int]] = []
        in_flight = 0
        for ts, delta in events:
            in_flight += delta
            timeline.append((ts - base, in_flight))
        return timeline

    @staticmethod
    def _log_timeline_chart(
            timeline,
    ) -> None:
        """Log a simple ASCII chart of concurrency over time."""
        if not timeline:
            return
        max_conc = max(c for _, c in timeline)
        total_duration = timeline[-1][0]
        if total_duration <= 0 or max_conc <= 0:
            return
        num_buckets = min(20, int(total_duration) + 1)
        bucket_size = total_duration / num_buckets
        bucket_peaks = [0] * num_buckets
        # Carry forward the in-flight count so buckets
        # without events reflect the actual state.
        current = 0
        event_idx = 0
        for i in range(num_buckets):
            bucket_end = (i + 1) * bucket_size
            bucket_peaks[i] = current
            while (event_idx < len(timeline)
                   and timeline[event_idx][0] < bucket_end):
                current = timeline[event_idx][1]
                bucket_peaks[i] = max(
                    bucket_peaks[i], current,
                )
                event_idx += 1
        for i, peak in enumerate(bucket_peaks):
            t_start = i * bucket_size
            chart = "#" * (peak * 40 // max_conc) if max_conc else ""
            label = Formatters.fmt_duration(t_start)
            logger.info(
                "    %8s |%-40s| %d",
                label, chart, peak,
            )
