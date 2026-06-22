# Copyright (C) 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
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

"""Write a human-readable summary.txt for load test results."""

import logging
import os
import time
from typing import Dict
from typing import List
from typing import Optional

from collections import Counter

from tests.load_tests.config import fmt_duration
from tests.load_tests.config import format_rss
from tests.load_tests.config import STATUS_CREATED

logger = logging.getLogger(__name__)


class SummaryFileWriter:
    """Writes a human-readable summary.txt to the output directory.

    Collects data from stage summaries and optional server timing
    to produce a single text file for quick review.
    """

    def __init__(
            self, stage_summaries, args,
            server_chat_timing=None,
    ) -> None:
        self._summaries = stage_summaries
        self._args = args
        self._server_timing = server_chat_timing or []

    def write(self, output_dir) -> Optional[str]:
        """Write summary.txt and return the file path."""
        lines = []
        self._write_header(lines)
        self._write_request_results(lines)
        self._write_completion_timeline(lines)
        self._write_server_timing(lines)

        path = os.path.join(output_dir, "summary.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        logger.info("  Summary:     %s", path)
        return path

    def _write_header(self, lines) -> None:
        """Write the test configuration header."""
        total_requests = sum(
            len(s.get("results", []))
            for s in self._summaries
        )
        total_elapsed = sum(
            s.get("elapsed", 0) for s in self._summaries
        )
        agent = self._args.agent
        date_str = time.strftime("%Y-%m-%d %H:%M")
        num_req = self._args.num_requests
        num_rnd = self._args.num_rounds
        workers = self._args.max_workers
        lines.append("=" * 60)
        lines.append("  LOAD TEST SUMMARY")
        lines.append("=" * 60)
        lines.append(f"  Agent:       {agent}")
        lines.append(f"  Date:        {date_str} UTC")
        lines.append(
            f"  Requests:    {num_req} x {num_rnd}"
            f" round(s) = {total_requests} total",
        )
        lines.append(f"  Workers:     {workers} (concurrent)")
        lines.append(
            f"  Total wall time:"
            f" {fmt_duration(total_elapsed, precision=1)}"
        )
        ttfr_values = [
            r.get("ttft", 0)
            for s in self._summaries
            for r in s.get("results", [])
            if r.get("ttft", 0) > 0
        ]
        if ttfr_values:
            avg_ttfr = sum(ttfr_values) / len(ttfr_values)
            lines.append(
                f"  Time to first response:"
                f" {fmt_duration(min(ttfr_values))} min"
                f" / {fmt_duration(avg_ttfr)} avg"
                f" / {fmt_duration(max(ttfr_values))} max"
            )
        durations = [
            r.get("elapsed", 0)
            for s in self._summaries
            for r in s.get("results", [])
        ]
        if durations:
            avg_dur = sum(durations) / len(durations)
            lines.append(
                f"  Request duration:"
                f" {fmt_duration(min(durations))} min"
                f" / {fmt_duration(avg_dur)} avg"
                f" / {fmt_duration(max(durations))} max"
            )
        llm_calls = [
            r.get("llm_calls", 0)
            for s in self._summaries
            for r in s.get("results", [])
            if r.get("llm_calls", 0) > 0
        ]
        if llm_calls:
            avg_calls = round(sum(llm_calls) / len(llm_calls))
            lines.append(
                f"  LLM calls:"
                f" {min(llm_calls)} min"
                f" / {avg_calls} avg"
                f" / {max(llm_calls)} max"
            )
        self._write_rss_trajectory(lines)
        self._write_validation_summary(lines)
        lines.append("")

    def _write_rss_trajectory(self, lines) -> None:
        """Write server RSS start/peak/end if available."""
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
            return
        lines.append(
            f"  Server RSS:"
            f" {format_rss(start_rss or 0)} start"
            f" \u2192 {format_rss(peak_rss)} peak"
            f" \u2192 {format_rss(end_rss or 0)} end"
        )

    def _write_validation_summary(self, lines) -> None:
        """Write validation retry summary if any events exist."""
        all_events = []
        for summary in self._summaries:
            all_events.extend(
                summary.get("validation_events", []),
            )
        if not all_events:
            return
        total_cycles = sum(
            e.get("fix_cycles", 0) for e in all_events
        )
        total_requests = sum(
            s.get("concurrent", 0) for s in self._summaries
        )
        affected = len(all_events)
        lines.append(
            f"  Validation: {affected} of {total_requests}"
            f" requests needed fixes"
            f" ({total_cycles} fix cycles total)"
        )
        self._write_validation_time_impact(
            lines, all_events,
        )
        all_errors = []
        for event in all_events:
            all_errors.extend(event.get("errors", []))
        if all_errors:
            counts = Counter(all_errors)
            top = counts.most_common(3)
            parts = [
                f"{err} ({cnt}x)" for err, cnt in top
            ]
            lines.append(
                f"    {len(all_errors)} errors found:"
                f" {', '.join(parts)}"
            )

    def _write_validation_time_impact(
            self, lines, events,
    ) -> None:
        """Write avg duration with/without validation fixes."""
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
            avg_without = (
                sum(without_fixes) / len(without_fixes)
            )
            lines.append(
                f"    Requests with fixes took"
                f" {fmt_duration(avg_with)} avg"
                f" vs {fmt_duration(avg_without)} avg"
                f" without"
            )

    def _write_request_results(self, lines) -> None:
        """Write per-request result table."""
        all_results = []
        for summary in self._summaries:
            all_results.extend(summary.get("results", []))
        if not all_results:
            return

        lines.append("=" * 60)
        lines.append("  REQUEST RESULTS")
        lines.append("=" * 60)

        for result in all_results:
            self._format_result_line(lines, result)

        self._format_result_totals(lines, all_results)

    def _format_result_line(self, lines, result) -> None:
        """Format a single request result line."""
        rid = result.get("request_id", "?")
        elapsed = result.get("elapsed", 0)
        status = result.get("status", "?")
        detail = self._extract_detail(result)
        if detail:
            lines.append(
                f"  {rid:<12s} {elapsed:7.1f}s"
                f"  {status:<8s}  {detail}",
            )
        else:
            lines.append(
                f"  {rid:<12s} {elapsed:7.1f}s"
                f"  {status:<8s}",
            )

    @staticmethod
    def _format_result_totals(lines, all_results) -> None:
        """Format overall totals for request results."""
        passed = sum(
            1 for r in all_results
            if r.get("status") == STATUS_CREATED
        )
        total = len(all_results)
        failed = total - passed
        latencies = [
            r.get("elapsed", 0) for r in all_results
        ]
        lines.append("")
        lines.append(
            f"  Overall: {passed}/{total} CREATED,"
            f" {failed} failed",
        )
        if latencies:
            avg = sum(latencies) / len(latencies)
            lines.append(
                f"  Avg: {avg:.1f}s"
                f" | Min: {min(latencies):.1f}s"
                f" | Max: {max(latencies):.1f}s",
            )
        lines.append("")

    def _write_completion_timeline(self, lines) -> None:
        """Write cumulative completion timeline."""
        all_latencies = []
        for summary in self._summaries:
            for result in summary.get("results", []):
                all_latencies.append(result.get("elapsed", 0))
        if not all_latencies:
            return

        all_latencies.sort()
        total = len(all_latencies)
        milestones = [50, 60, 70, 80, 90, 95, 100]
        lines.append("=" * 60)
        lines.append("  COMPLETION TIMELINE")
        lines.append("=" * 60)

        prev_count = -1
        for pct in milestones:
            idx = min(
                int(total * pct / 100 + 0.999999) - 1,
                total - 1,
            )
            count = idx + 1
            val = all_latencies[idx]
            if count == prev_count:
                continue
            prev_count = count
            lines.append(
                f"  {pct:4d}% ({count} requests)"
                f" completed by"
                f" {fmt_duration(val, precision=1)}",
            )
        self._write_count_milestones(lines, all_latencies)
        lines.append("")

    @staticmethod
    def _write_count_milestones(lines, sorted_latencies):
        """Write completion times at round-number request counts."""
        total = len(sorted_latencies)
        step = 50
        if total < step:
            return
        milestones = list(range(step, total, step))
        if milestones[-1] != total:
            milestones.append(total)
        lines.append("")
        lines.append("  Completion by count:")
        for count in milestones:
            duration = sorted_latencies[count - 1]
            lines.append(
                f"  {count:5d} requests completed by"
                f" {fmt_duration(duration, precision=1)}",
            )

    def _write_server_timing(self, lines) -> None:
        """Write per-request server timing breakdown."""
        if not self._server_timing:
            return

        client_results = self._collect_client_times()
        by_server_id: Dict[str, list] = {}
        for entry in self._server_timing:
            sid = entry.get("request_id", "")
            by_server_id.setdefault(sid, []).append(entry)

        lines.append("=" * 60)
        lines.append("  SERVER TIMING BREAKDOWN")
        lines.append("=" * 60)

        for sid in sorted(by_server_id.keys()):
            entries = by_server_id[sid]
            entries.sort(
                key=lambda e: e.get("start_ts", 0),
            )
            if not entries:
                continue
            top_start = entries[0].get("start_ts", 0)
            client = self._match_client(
                top_start, client_results,
            )
            label = client.get("id", sid)
            self._format_request_timing(
                lines, label, entries, client,
            )
        lines.append("")

    def _collect_client_times(
            self,
    ) -> List[Dict[str, float]]:
        """Collect client start/end times from all results."""
        results: List[Dict[str, float]] = []
        for summary in self._summaries:
            for result in summary.get("results", []):
                rid = result.get("request_id", "")
                start = result.get("start_time", 0)
                end = result.get("end_time", 0)
                if rid and start and end:
                    results.append({
                        "id": rid,
                        "start": start,
                        "end": end,
                    })
        return results

    @staticmethod
    def _match_client(
            server_start_ts, client_results,
    ) -> Dict[str, float]:
        """Find the client request whose window contains the ts."""
        for client in client_results:
            if (client.get("start", 0)
                    <= server_start_ts
                    <= client.get("end", 0)):
                return client
        return {}

    @staticmethod
    def _format_request_timing(
            lines, rid, entries, client,
    ) -> None:
        """Format timing breakdown for a single request."""
        top = entries[0]
        top_agent = top.get("agent", "?")
        c_start = client.get("start", 0)
        c_end = client.get("end", 0)
        total = (
            c_end - c_start if c_start and c_end else 0
        )
        s_start = top.get("start_ts", 0)
        s_finish = top.get("finish_ts", 0)
        lines.append("")
        lines.append(f"  {rid} ({total:.1f}s total):")
        if c_start and s_start and s_start > c_start:
            lines.append(
                f"    Client -> Server: "
                f" {s_start - c_start:6.1f}s",
            )
        lines.append(
            f"    Server: {top_agent:<25s}"
            f" {top.get('duration', 0):6.1f}s",
        )
        SummaryFileWriter._format_sub_agents(
            lines, entries, top_agent,
        )
        if c_end and s_finish and c_end > s_finish:
            lines.append(
                f"    Server -> Client: "
                f" {c_end - s_finish:6.1f}s",
            )

    @staticmethod
    def _format_sub_agents(
            lines, entries, top_agent,
    ) -> None:
        """Format sub-agent timing lines."""
        sub_agents = [
            e for e in entries
            if e.get("agent") != top_agent
        ]
        for i, sub in enumerate(sub_agents):
            prefix = (
                "\u2514\u2500"
                if i == len(sub_agents) - 1
                else "\u251c\u2500"
            )
            name = sub.get("agent", "?")
            dur = sub.get("duration", 0)
            lines.append(
                f"      {prefix} {name:<23s} {dur:6.1f}s",
            )

    @staticmethod
    def _extract_detail(result) -> str:
        """Extract a human-readable detail from parsed fields."""
        parts = []
        for key in ("agent_network_name", "reservation_id"):
            val = result.get(key, "")
            if val:
                parts.append(str(val))
                break
        reason = result.get("failure_reason")
        if reason:
            parts.append(f"reason: {reason}")
        return "  ".join(parts)
