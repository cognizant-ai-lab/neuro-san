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

"""Summary reporting — ramp-up and overall results."""

import logging

from collections import Counter

from tests.load_tests.config import fmt_duration
from tests.load_tests.config import format_rss
from tests.load_tests.config import SEPARATOR_WIDTH
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.reporting.table_formatter import TableFormatter

logger = logging.getLogger(__name__)


class SummaryReporter:
    """Logs ramp-up and overall results across all stages.

    Holds the collected stage summaries so that multiple
    reporting methods can access them without re-passing.
    """

    def __init__(self, stage_summaries) -> None:
        self._summaries = stage_summaries

    def log_ramp_summary(self, *, is_ramp=True) -> None:
        """Log the ramp-up summary table across all stages."""
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        title = "RAMP-UP SUMMARY" if is_ramp else "ROUND SUMMARY"
        logger.info("  %s", title)
        logger.info("=" * SEPARATOR_WIDTH)

        has_server_counts = any(
            summary.get("primary_started") is not None
            for summary in self._summaries
        )
        first_col = "Stage" if is_ramp else "Round"
        header = [
            first_col, "Concurrent", "Created", "Failed",
            "Timeout", "Killed", "Retries", "Amplification",
            "Duration",
        ]
        if has_server_counts:
            header.extend(["Recv", "Done", "Internal"])
        rows = []
        for summary in self._summaries:
            counts = summary.get("counts", {})
            row = (
                str(summary.get("stage") if is_ramp
                    else summary.get("round", summary.get("stage"))),
                str(summary.get("concurrent")),
                str(counts.get(STATUS_CREATED, 0)),
                str(counts.get(STATUS_FAILED, 0)),
                str(counts.get(STATUS_TIMEOUT, 0)),
                str(counts.get(STATUS_KILLED, 0)),
                str(summary.get("total_retries", 0)),
                f"{summary.get('amplification', 1.0):.2f}x",
                f"{summary.get('elapsed', 0):.1f}s",
            )
            if has_server_counts:
                pri_started = summary.get("primary_started")
                pri_finished = summary.get("primary_finished")
                total_started = summary.get("total_started")
                internal = (
                    str(total_started - pri_started)
                    if pri_started is not None
                    and total_started is not None
                    else "-"
                )
                row += (
                    str(pri_started)
                    if pri_started is not None else "-",
                    str(pri_finished)
                    if pri_finished is not None else "-",
                    internal,
                )
            rows.append(row)
        TableFormatter.log_table(header, rows)

    def log_overall_results(self) -> None:
        """Log overall results across all stages."""
        total_created = 0
        total_failed = 0
        total_timeout = 0
        total_killed = 0
        total_time = 0.0
        total_retries = 0

        for summary in self._summaries:
            counts = summary.get("counts", {})
            total_created += counts.get(STATUS_CREATED, 0)
            total_failed += counts.get(STATUS_FAILED, 0)
            total_timeout += counts.get(STATUS_TIMEOUT, 0)
            total_killed += counts.get(STATUS_KILLED, 0)
            total_time += summary.get("elapsed", 0)
            total_retries += summary.get("total_retries", 0)

        total_sent = (
            total_created + total_failed + total_timeout + total_killed
        )

        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  OVERALL RESULTS")
        logger.info("=" * SEPARATOR_WIDTH)
        logger.info("  Total requests: %s", total_sent)
        logger.info("    Created:   %s", total_created)
        logger.info("    Failed:    %s", total_failed)
        logger.info("    Timed out: %s", total_timeout)
        logger.info("    Killed:    %s", total_killed)
        logger.info(
            "  Total wall time: %s",
            fmt_duration(total_time, precision=2),
        )
        self._log_performance_stats()

        if total_retries > 0:
            total_requests = sum(
                s.get("concurrent", 0)
                for s in self._summaries
            )
            amplification = (
                (total_requests + total_retries) / total_requests
                if total_requests > 0 else 1.0
            )
            logger.info("\n  Overall max_attempts retry totals:")
            logger.info("    Total retries:   %s", total_retries)
            logger.info(
                "    Amplification:   %.2fx", amplification,
            )

    def _log_performance_stats(self) -> None:
        """Log TTFR, duration, LLM calls, and RSS trajectory."""
        ttfr = self._ttfr_stats()
        if ttfr is not None:
            logger.info(
                "  Time to first response: %s min"
                " / %s avg / %s max",
                fmt_duration(ttfr["min"]),
                fmt_duration(ttfr["avg"]),
                fmt_duration(ttfr["max"]),
            )

        duration = self._request_duration_stats()
        if duration is not None:
            logger.info(
                "  Request duration: %s min / %s avg"
                " / %s max",
                fmt_duration(duration["min"]),
                fmt_duration(duration["avg"]),
                fmt_duration(duration["max"]),
            )

        llm_stats = self._llm_call_stats()
        if llm_stats is not None:
            logger.info(
                "  LLM calls: %s min / %s avg / %s max",
                llm_stats["min"], llm_stats["avg"],
                llm_stats["max"],
            )

        rss_trajectory = self._rss_trajectory()
        if rss_trajectory is not None:
            logger.info(
                "  Server RSS: %s start \u2192 %s peak"
                " \u2192 %s end",
                format_rss(rss_trajectory["start"]),
                format_rss(rss_trajectory["peak"]),
                format_rss(rss_trajectory["end"]),
            )

        self._log_validation_summary()

    def _request_duration_stats(self):
        """Compute min/avg/max elapsed time across requests."""
        durations = []
        for summary in self._summaries:
            for result in summary.get("results", []):
                durations.append(result.get("elapsed", 0))
        if not durations:
            return None
        return {
            "min": min(durations),
            "avg": sum(durations) / len(durations),
            "max": max(durations),
        }

    def _llm_call_stats(self):
        """Compute min/avg/max LLM calls per request."""
        calls = []
        for summary in self._summaries:
            for result in summary.get("results", []):
                llm = result.get("llm_calls", 0)
                if llm > 0:
                    calls.append(llm)
        if not calls:
            return None
        return {
            "min": min(calls),
            "avg": round(sum(calls) / len(calls)),
            "max": max(calls),
        }

    def _ttfr_stats(self):
        """Compute min/avg/max time-to-first-response."""
        values = []
        for summary in self._summaries:
            for result in summary.get("results", []):
                ttfr = result.get("ttft", 0)
                if ttfr > 0:
                    values.append(ttfr)
        if not values:
            return None
        return {
            "min": min(values),
            "avg": sum(values) / len(values),
            "max": max(values),
        }

    def _rss_trajectory(self):
        """Find start, peak, and end RSS across all stages."""
        start_rss = None
        end_rss = None
        peak_rss = None
        for summary in self._summaries:
            before = summary.get("before_server_rss")
            after = summary.get("after_server_rss")
            peak = summary.get("peak_server_rss")
            if before is not None and start_rss is None:
                start_rss = before
            if after is not None:
                end_rss = after
            if peak is not None:
                if peak_rss is None or peak > peak_rss:
                    peak_rss = peak
        if peak_rss is None:
            return None
        return {
            "start": start_rss or 0,
            "peak": peak_rss,
            "end": end_rss or 0,
        }

    def _log_validation_summary(self) -> None:
        """Log aggregate validation retry info if any."""
        all_events = self._collect_validation_events()
        if not all_events:
            return
        total_cycles = sum(
            e.get("fix_cycles", 0) for e in all_events
        )
        total_requests = sum(
            s.get("concurrent", 0) for s in self._summaries
        )
        affected = len(all_events)
        all_errors = []
        for event in all_events:
            all_errors.extend(event.get("errors", []))
        logger.info(
            "\n  Validation: %s of %s requests needed"
            " fixes (%s fix cycles total)",
            affected, total_requests, total_cycles,
        )
        self._log_validation_time_impact(all_events)
        if all_errors:
            self._log_top_errors(all_errors)

    def _log_validation_time_impact(self, events) -> None:
        """Log avg duration of requests with/without fixes."""
        fix_rids = {e.get("request_id") for e in events}
        with_fixes = []
        without_fixes = []
        for summary in self._summaries:
            for result in summary.get("results", []):
                rid = result.get("request_id", "")
                elapsed = result.get("elapsed", 0)
                if rid in fix_rids:
                    with_fixes.append(elapsed)
                else:
                    without_fixes.append(elapsed)
        if with_fixes and without_fixes:
            avg_with = sum(with_fixes) / len(with_fixes)
            avg_without = sum(without_fixes) / len(without_fixes)
            logger.info(
                "    Requests with fixes took %s avg"
                " vs %s avg without",
                fmt_duration(avg_with),
                fmt_duration(avg_without),
            )

    @staticmethod
    def _log_top_errors(all_errors) -> None:
        """Log the most common validation errors."""
        counts = Counter(all_errors)
        top = counts.most_common(3)
        parts = [
            f"{err} ({cnt}x)" for err, cnt in top
        ]
        logger.info(
            "    %s errors found: %s",
            len(all_errors), ", ".join(parts),
        )

    def _collect_validation_events(self):
        """Gather all validation events across stages."""
        events = []
        for summary in self._summaries:
            events.extend(
                summary.get("validation_events", []),
            )
        return events
