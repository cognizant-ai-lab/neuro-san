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

"""Write a human-readable summary.txt for load test results."""

import logging
import os
import time
from argparse import Namespace
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple

from collections import Counter

import psutil

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.reporting.formatters import Formatters

logger: logging.Logger = logging.getLogger(__name__)


class SummaryFileWriter:
    """Writes a human-readable summary.txt to the output directory.

    Collects data from stage summaries and optional server timing
    to produce a single text file for quick review.
    """

    def __init__(self, stage_summaries: List[Dict[str, Any]], args: Namespace,
                 server_chat_timing: Optional[List[Dict[str, Any]]] = None) -> None:
        """
        Constructor.

        :param stage_summaries: Per-stage summaries collected during the run
        :param args: Parsed load-test command line
        :param server_chat_timing: Per-agent timing entries from the server log, or None
        """
        self._summaries: List[Dict[str, Any]] = stage_summaries
        self._args: Namespace = args
        self._server_timing: List[Dict[str, Any]] = server_chat_timing or []

    def write(self, output_dir: str) -> str:
        """
        Write summary.txt and return the file path.

        :param output_dir: Directory to write summary.txt into
        :return: Path of summary.txt
        """
        lines: List[str] = []
        self._write_header(lines)
        self._write_request_results(lines)
        self._write_completion_timeline(lines)
        self._write_server_timing(lines)

        path: str = os.path.join(output_dir, "summary.txt")
        with open(path, "w", encoding="utf-8") as file_handle:
            file_handle.write("\n".join(lines) + "\n")
        logger.info("  Summary:     %s", path)
        return path

    def _write_header(self, lines: List[str]) -> None:
        """
        Write the test configuration header.

        :param lines: Summary lines, appended to in place
        """
        total_requests: int = sum(
            len(stage_summary.get("results", []))
            for stage_summary in self._summaries
        )
        total_elapsed_seconds: float = sum(
            stage_summary.get("elapsed", 0) for stage_summary in self._summaries
        )
        agent: str = self._args.agent
        date_text: str = time.strftime("%Y-%m-%d %H:%M")
        request_count: int = self._args.num_requests
        round_count: int = self._args.num_rounds
        workers: int = self._args.max_workers
        lines.append("=" * 60)
        lines.append("  LOAD TEST SUMMARY")
        lines.append("=" * 60)
        lines.append(f"  Agent:       {agent}")
        lines.append(f"  Date:        {date_text} UTC")
        lines.append(f"  Requests:    {request_count} x {round_count} round(s) = {total_requests} total")
        lines.append(f"  Workers:     {workers} (concurrent)")
        lines.append(f"  Total wall time: {Formatters.fmt_duration(total_elapsed_seconds, precision=1)}")
        first_response_seconds: List[float] = self._time_to_first_response_values()
        if first_response_seconds:
            average_first_response_seconds: float = sum(first_response_seconds) / len(first_response_seconds)
            lines.append(
                f"  Time to first response: {Formatters.fmt_duration(min(first_response_seconds))} min"
                f" / {Formatters.fmt_duration(average_first_response_seconds)} avg"
                f" / {Formatters.fmt_duration(max(first_response_seconds))} max"
            )
        durations_seconds: List[float] = [
            result.get("elapsed", 0)
            for stage_summary in self._summaries
            for result in stage_summary.get("results", [])
        ]
        if durations_seconds:
            average_duration_seconds: float = sum(durations_seconds) / len(durations_seconds)
            lines.append(
                f"  Request duration: {Formatters.fmt_duration(min(durations_seconds))} min"
                f" / {Formatters.fmt_duration(average_duration_seconds)} avg"
                f" / {Formatters.fmt_duration(max(durations_seconds))} max"
            )
        llm_calls: List[int] = [
            result.get("llm_calls", 0)
            for stage_summary in self._summaries
            for result in stage_summary.get("results", [])
            if result.get("llm_calls", 0) > 0
        ]
        if llm_calls:
            average_calls: int = round(sum(llm_calls) / len(llm_calls))
            lines.append(f"  LLM calls: {min(llm_calls)} min / {average_calls} avg / {max(llm_calls)} max")
        self._write_rss_trajectory(lines)
        self._write_client_rss_trajectory(lines)
        self._write_sys_mem_trajectory(lines)
        self._write_validation_summary(lines)
        lines.append("")

    def _time_to_first_response_values(self) -> List[float]:
        """
        Collect the time to first response of every request that got one.

        :return: Seconds to first response per request, zeros left out
        """
        first_response_seconds: List[float] = []
        summary: Dict[str, Any]
        for summary in self._summaries:
            result: Dict[str, Any]
            for result in summary.get("results", []):
                time_to_first_response_seconds: float = result.get("time_to_first_response", 0)
                if time_to_first_response_seconds > 0:
                    first_response_seconds.append(time_to_first_response_seconds)
        return first_response_seconds

    def _write_rss_trajectory(self, lines: List[str]) -> None:
        """
        Write server RSS start/peak/end if available.

        :param lines: Summary lines, appended to in place
        """
        start_rss_megabytes: Optional[float] = None
        end_rss_megabytes: Optional[float] = None
        peak_rss_megabytes: Optional[float] = None
        for summary in self._summaries:
            before_rss_megabytes: Optional[float] = summary.get("before_server_rss")
            after_rss_megabytes: Optional[float] = summary.get("after_server_rss")
            stage_peak_rss_megabytes: Optional[float] = summary.get("peak_server_rss")
            if before_rss_megabytes is not None and start_rss_megabytes is None:
                start_rss_megabytes = before_rss_megabytes
            if after_rss_megabytes is not None:
                end_rss_megabytes = after_rss_megabytes
            if stage_peak_rss_megabytes is not None:
                if peak_rss_megabytes is None or stage_peak_rss_megabytes > peak_rss_megabytes:
                    peak_rss_megabytes = stage_peak_rss_megabytes
        if peak_rss_megabytes is None:
            return
        lines.append(
            f"  Server RSS: {Formatters.format_rss(start_rss_megabytes or 0)} start"
            f" \u2192 {Formatters.format_rss(peak_rss_megabytes)} peak"
            f" \u2192 {Formatters.format_rss(end_rss_megabytes or 0)} end"
        )

    def _write_client_rss_trajectory(self, lines: List[str]) -> None:
        """
        Write client RSS start/peak/end if available.

        :param lines: Summary lines, appended to in place
        """
        start_rss_megabytes: Optional[float] = None
        end_rss_megabytes: Optional[float] = None
        peak_rss_megabytes: Optional[float] = None
        for summary in self._summaries:
            before_rss_megabytes: Optional[float] = summary.get("before_client_rss")
            after_rss_megabytes: Optional[float] = summary.get("after_client_rss")
            stage_peak_rss_megabytes: Optional[float] = summary.get("peak_client_rss")
            if before_rss_megabytes is not None and start_rss_megabytes is None:
                start_rss_megabytes = before_rss_megabytes
            if after_rss_megabytes is not None:
                end_rss_megabytes = after_rss_megabytes
            if stage_peak_rss_megabytes is not None:
                if peak_rss_megabytes is None or stage_peak_rss_megabytes > peak_rss_megabytes:
                    peak_rss_megabytes = stage_peak_rss_megabytes
        if peak_rss_megabytes is None:
            return
        lines.append(
            f"  Client RSS: {Formatters.format_rss(start_rss_megabytes or 0)} start"
            f" \u2192 {Formatters.format_rss(peak_rss_megabytes)} peak"
            f" \u2192 {Formatters.format_rss(end_rss_megabytes or 0)} end"
        )

    def _write_sys_mem_trajectory(self, lines: List[str]) -> None:
        """
        Write system memory start/peak/end if available.

        :param lines: Summary lines, appended to in place
        """
        start_memory_percentage: Optional[float] = None
        end_memory_percentage: Optional[float] = None
        peak_memory_percentage: Optional[float] = None
        peak_available_gigabytes: Optional[float] = None
        for summary in self._summaries:
            before_memory_percentage: Optional[float] = summary.get("before_sys_mem_pct")
            after_memory_percentage: Optional[float] = summary.get("after_sys_mem_pct")
            stage_peak_memory_percentage: Optional[float] = summary.get("peak_sys_mem_pct")
            available_gigabytes: Optional[float] = summary.get("peak_sys_mem_avail_gb")
            if before_memory_percentage is not None and start_memory_percentage is None:
                start_memory_percentage = before_memory_percentage
            if after_memory_percentage is not None:
                end_memory_percentage = after_memory_percentage
            if stage_peak_memory_percentage is not None:
                if peak_memory_percentage is None or stage_peak_memory_percentage > peak_memory_percentage:
                    peak_memory_percentage = stage_peak_memory_percentage
                    peak_available_gigabytes = available_gigabytes
        if peak_memory_percentage is None:
            return
        total_gigabytes: float = psutil.virtual_memory().total / (1024 ** 3)
        peak_detail: str = (
            f"{peak_memory_percentage:.0f}% peak ({peak_available_gigabytes or 0:.1f}G free / {total_gigabytes:.1f}G)"
        )
        lines.append(
            f"  System memory: {start_memory_percentage or 0:.0f}% start \u2192 {peak_detail}"
            f" \u2192 {end_memory_percentage or 0:.0f}% end"
        )

    def _write_validation_summary(self, lines: List[str]) -> None:
        """
        Write validation retry summary if any events exist.

        :param lines: Summary lines, appended to in place
        """
        all_events: List[Dict[str, Any]] = []
        for summary in self._summaries:
            all_events.extend(summary.get("validation_events", []))
        if not all_events:
            return
        total_cycles: int = sum(
            event.get("fix_cycles", 0) for event in all_events
        )
        total_requests: int = sum(
            stage_summary.get("concurrent", 0) for stage_summary in self._summaries
        )
        affected: int = len(all_events)
        lines.append(
            f"  Validation: {affected} of {total_requests} requests needed fixes ({total_cycles} fix cycles total)"
        )
        self._write_validation_time_impact(lines, all_events)
        all_errors: List[str] = []
        for event in all_events:
            all_errors.extend(event.get("errors", []))
        if all_errors:
            counts: Counter = Counter(all_errors)
            top: List[Tuple[str, int]] = counts.most_common(3)
            parts: List[str] = [
                f"{error} ({count}x)" for error, count in top
            ]
            lines.append(f"    {len(all_errors)} errors found: {', '.join(parts)}")

    def _write_validation_time_impact(self, lines: List[str], events: List[Dict[str, Any]]) -> None:
        """
        Write avg duration with/without validation fixes.

        :param lines: Summary lines, appended to in place
        :param events: Validation events from every stage
        """
        fix_request_ids: Set[str] = {event.get("request_id") for event in events}
        durations_with_fixes_seconds: List[float] = []
        durations_without_fixes_seconds: List[float] = []
        for summary in self._summaries:
            for result in summary.get("results", []):
                request_id: str = result.get("request_id", "")
                elapsed_seconds: float = result.get("elapsed", 0)
                if request_id in fix_request_ids:
                    durations_with_fixes_seconds.append(elapsed_seconds)
                else:
                    durations_without_fixes_seconds.append(elapsed_seconds)
        if durations_with_fixes_seconds and durations_without_fixes_seconds:
            average_with_fixes_seconds: float = sum(durations_with_fixes_seconds) / len(durations_with_fixes_seconds)
            average_without_fixes_seconds: float = (
                sum(durations_without_fixes_seconds) / len(durations_without_fixes_seconds)
            )
            lines.append(
                f"    Requests with fixes took {Formatters.fmt_duration(average_with_fixes_seconds)} avg"
                f" vs {Formatters.fmt_duration(average_without_fixes_seconds)} avg without"
            )

    def _write_request_results(self, lines: List[str]) -> None:
        """
        Write per-request result table.

        :param lines: Summary lines, appended to in place
        """
        all_results: List[Dict[str, Any]] = []
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

    def _format_result_line(self, lines: List[str], result: Dict[str, Any]) -> None:
        """
        Format a single request result line.

        :param lines: Summary lines, appended to in place
        :param result: One request result
        """
        request_id: str = result.get("request_id", "?")
        elapsed_seconds: float = result.get("elapsed", 0)
        status: str = result.get("status", "?")
        detail: str = self._extract_detail(result)
        if detail:
            lines.append(f"  {request_id:<12s} {elapsed_seconds:7.1f}s  {status:<8s}  {detail}")
        else:
            lines.append(f"  {request_id:<12s} {elapsed_seconds:7.1f}s  {status:<8s}")

    @staticmethod
    def _format_result_totals(lines: List[str], all_results: List[Dict[str, Any]]) -> None:
        """
        Format overall totals for request results.

        :param lines: Summary lines, appended to in place
        :param all_results: Every request result
        """
        passed: int = sum(
            1 for result in all_results
            if result.get("status") == STATUS_CREATED
        )
        total: int = len(all_results)
        failed: int = total - passed
        latencies_seconds: List[float] = [
            result.get("elapsed", 0) for result in all_results
        ]
        lines.append("")
        lines.append(f"  Overall: {passed}/{total} CREATED, {failed} failed")
        if latencies_seconds:
            average_latency_seconds: float = sum(latencies_seconds) / len(latencies_seconds)
            lines.append(
                f"  Avg: {average_latency_seconds:.1f}s | Min: {min(latencies_seconds):.1f}s"
                f" | Max: {max(latencies_seconds):.1f}s",
            )
        lines.append("")

    def _write_completion_timeline(self, lines: List[str]) -> None:
        """
        Write cumulative completion timeline.

        :param lines: Summary lines, appended to in place
        """
        all_latencies_seconds: List[float] = []
        for summary in self._summaries:
            for result in summary.get("results", []):
                all_latencies_seconds.append(result.get("elapsed", 0))
        if not all_latencies_seconds:
            return

        all_latencies_seconds.sort()
        total: int = len(all_latencies_seconds)
        milestones: List[int] = [50, 60, 70, 80, 90, 95, 100]
        lines.append("=" * 60)
        lines.append("  COMPLETION TIMELINE")
        lines.append("=" * 60)

        previous_count: int = -1
        for percentage in milestones:
            index: int = min(int(total * percentage / 100 + 0.999999) - 1, total - 1)
            count: int = index + 1
            latency_seconds: float = all_latencies_seconds[index]
            if count == previous_count:
                continue
            previous_count = count
            lines.append(
                f"  {percentage:4d}% ({count} requests) completed by"
                f" {Formatters.fmt_duration(latency_seconds, precision=1)}",
            )
        self._write_count_milestones(lines, all_latencies_seconds)
        lines.append("")

    @staticmethod
    def _write_count_milestones(lines: List[str], sorted_latencies_seconds: List[float]) -> None:
        """
        Write completion times at round-number request counts.

        :param lines: Summary lines, appended to in place
        :param sorted_latencies_seconds: Request latencies in seconds, sorted in ascending order
        """
        total: int = len(sorted_latencies_seconds)
        step: int = 50
        if total <= step:
            return
        milestones: List[int] = list(range(step, total, step))
        if not milestones or milestones[-1] != total:
            milestones.append(total)
        lines.append("")
        lines.append("  Completion by count:")
        for count in milestones:
            duration_seconds: float = sorted_latencies_seconds[count - 1]
            lines.append(f"  {count:5d} requests completed by {Formatters.fmt_duration(duration_seconds, precision=1)}")

    def _write_server_timing(self, lines: List[str]) -> None:
        """
        Write per-request server timing breakdown.

        :param lines: Summary lines, appended to in place
        """
        if not self._server_timing:
            return

        client_results: List[Dict[str, Any]] = self._collect_client_times()
        by_server_id: Dict[str, list] = {}
        for entry in self._server_timing:
            server_request_id: str = entry.get("request_id", "")
            by_server_id.setdefault(server_request_id, []).append(entry)

        lines.append("=" * 60)
        lines.append("  SERVER TIMING BREAKDOWN")
        lines.append("=" * 60)

        for server_request_id in sorted(by_server_id.keys()):
            entries: List[Dict[str, Any]] = by_server_id[server_request_id]
            entries.sort(
                key=lambda timing_entry: timing_entry.get("start_ts", 0),
            )
            if not entries:
                continue
            top_start_seconds: float = entries[0].get("start_ts", 0)
            client: Dict[str, Any] = self._match_client(top_start_seconds, client_results)
            label: str = client.get("id", server_request_id)
            self._format_request_timing(lines, label, entries, client)
        lines.append("")

    def _collect_client_times(self) -> List[Dict[str, Any]]:
        """
        Collect client start/end times from all results.

        :return: id, start and end of each result that has both times
        """
        results: List[Dict[str, Any]] = []
        for summary in self._summaries:
            for result in summary.get("results", []):
                request_id: str = result.get("request_id", "")
                start_time_seconds: float = result.get("start_time", 0)
                end_time_seconds: float = result.get("end_time", 0)
                if request_id and start_time_seconds and end_time_seconds:
                    results.append({"id": request_id, "start": start_time_seconds, "end": end_time_seconds})
        return results

    @staticmethod
    def _match_client(server_start_seconds: float, client_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Find the client request whose window contains the server start time.

        :param server_start_seconds: Start time of the top-level server timing entry
        :param client_results: Client times from _collect_client_times
        :return: The matching client entry, or {} when none matches
        """
        for client in client_results:
            if client.get("start", 0) <= server_start_seconds <= client.get("end", 0):
                return client
        return {}

    @staticmethod
    def _format_request_timing(lines: List[str], request_id: str, entries: List[Dict[str, Any]],
                               client: Dict[str, Any]) -> None:
        """
        Format timing breakdown for a single request.

        :param lines: Summary lines, appended to in place
        :param request_id: Request label: the client request id, or the server id when no client matched
        :param entries: Server timing entries of the request, sorted by start time; the first is the top-level agent
        :param client: Matching client entry, or {} when none matched
        """
        top: Dict[str, Any] = entries[0]
        top_agent: str = top.get("agent", "?")
        client_start_seconds: float = client.get("start", 0)
        client_end_seconds: float = client.get("end", 0)
        total_duration_seconds: float = (
            client_end_seconds - client_start_seconds if client_start_seconds and client_end_seconds else 0
        )
        server_start_seconds: float = top.get("start_ts", 0)
        server_finish_seconds: float = top.get("finish_ts", 0)
        lines.append("")
        lines.append(f"  {request_id} ({total_duration_seconds:.1f}s total):")
        if client_start_seconds and server_start_seconds and server_start_seconds > client_start_seconds:
            lines.append(f"    Client -> Server:  {server_start_seconds - client_start_seconds:6.1f}s")
        lines.append(f"    Server: {top_agent:<25s} {top.get('duration_seconds', 0):6.1f}s")
        SummaryFileWriter._format_sub_agents(lines, entries, top_agent)
        if client_end_seconds and server_finish_seconds and client_end_seconds > server_finish_seconds:
            lines.append(f"    Server -> Client:  {client_end_seconds - server_finish_seconds:6.1f}s")

    @staticmethod
    def _format_sub_agents(lines: List[str], entries: List[Dict[str, Any]], top_agent: str) -> None:
        """
        Format sub-agent timing lines.

        :param lines: Summary lines, appended to in place
        :param entries: Server timing entries of the request
        :param top_agent: Name of the top-level agent, left out of the list
        """
        sub_agents: List[Dict[str, Any]] = [
            timing_entry for timing_entry in entries
            if timing_entry.get("agent") != top_agent
        ]
        for index, sub_agent in enumerate(sub_agents):
            prefix: str = (
                "\u2514\u2500"
                if index == len(sub_agents) - 1
                else "\u251c\u2500"
            )
            name: str = sub_agent.get("agent", "?")
            duration_seconds: float = sub_agent.get("duration_seconds", 0)
            lines.append(f"      {prefix} {name:<23s} {duration_seconds:6.1f}s")

    @staticmethod
    def _extract_detail(result: Dict[str, Any]) -> str:
        """
        Extract a human-readable detail from parsed fields.

        :param result: One request result
        :return: Network name or reservation id, then failure reason; empty when neither is set
        """
        parts: List[str] = []
        for key in ("agent_network_name", "reservation_id"):
            value: Optional[str] = result.get(key, "")
            if value:
                parts.append(str(value))
                break
        reason: Optional[str] = result.get("failure_reason")
        if reason:
            parts.append(f"reason: {reason}")
        return "  ".join(parts)
