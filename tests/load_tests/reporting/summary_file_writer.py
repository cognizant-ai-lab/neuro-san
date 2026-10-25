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
from os.path import join
from time import strftime
from argparse import Namespace
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple

from collections import Counter

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.latency_analyzer import LatencyAnalyzer
from tests.load_tests.reporting.system_resources import SystemResources

logger: logging.Logger = logging.getLogger(__name__)


class SummaryFileWriter:
    """
    Writes a human-readable summary.txt to the output directory.

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

        path: str = join(output_dir, "summary.txt")
        with open(path, "w", encoding="utf-8") as file_handle:
            file_handle.write("\n".join(lines) + "\n")
        logger.info("  Summary:     %s", path)
        return path

    def _write_header(self, lines: List[str]) -> None:
        """
        Write the test configuration header.

        :param lines: Summary lines, appended to in place
        """
        total_requests: int = 0
        # Floats are collected for sum(), which rounds better than a += loop, so the totals match the old code.
        stage_durations_seconds: List[float] = []
        stage_summary: Dict[str, Any]
        # Add up the requests and collect the wall time of every stage.
        for stage_summary in self._summaries:
            total_requests += len(stage_summary.get("results", []))
            stage_durations_seconds.append(stage_summary.get("elapsed", 0))
        total_elapsed_seconds: float = sum(stage_durations_seconds)
        agent: str = self._args.agent
        date_text: str = strftime("%Y-%m-%d %H:%M")
        request_count: int = self._args.num_requests
        round_count: int = self._args.num_rounds
        workers: int = self._args.max_workers
        lines.append(Formatters.SEPARATOR_LINE)
        lines.append("  LOAD TEST SUMMARY")
        lines.append(Formatters.SEPARATOR_LINE)
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
        self._write_request_stats(lines)
        self._write_rss_trajectory(lines)
        self._write_client_rss_trajectory(lines)
        self._write_sys_mem_trajectory(lines)
        self._write_validation_summary(lines)
        lines.append("")

    def _write_request_stats(self, lines: List[str]) -> None:
        """
        Write the min/avg/max request duration and LLM call count lines.

        :param lines: Summary lines, appended to in place
        """
        durations_seconds: List[float] = []
        llm_calls: List[int] = []
        stage_summary: Dict[str, Any]
        # Go through the requests of every stage.
        for stage_summary in self._summaries:
            result: Dict[str, Any]
            # Collect each request's duration, and its LLM call count when it made any calls.
            for result in stage_summary.get("results", []):
                durations_seconds.append(result.get("elapsed", 0))
                call_count: int = result.get("llm_calls", 0)
                if call_count > 0:
                    llm_calls.append(call_count)
        if durations_seconds:
            average_duration_seconds: float = sum(durations_seconds) / len(durations_seconds)
            lines.append(
                f"  Request duration: {Formatters.fmt_duration(min(durations_seconds))} min"
                f" / {Formatters.fmt_duration(average_duration_seconds)} avg"
                f" / {Formatters.fmt_duration(max(durations_seconds))} max"
            )
        if llm_calls:
            average_calls: int = round(sum(llm_calls) / len(llm_calls))
            lines.append(f"  LLM calls: {min(llm_calls)} min / {average_calls} avg / {max(llm_calls)} max")

    def _time_to_first_response_values(self) -> List[float]:
        """
        Collect the time to first response of every request that got one.

        :return: Seconds to first response per request, zeros left out
        """
        first_response_seconds: List[float] = []
        summary: Dict[str, Any]
        # Collect the time to first response of every request.
        for summary in self._summaries:
            result: Dict[str, Any]
            # Keep only the requests that got a first response.
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
        summary: Dict[str, Any]
        # Track the first, last and peak server RSS over the stages.
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
        # The arrow "→" leads from start to peak to end; plain "->" would change the summary text.
        lines.append(
            f"  Server RSS: {Formatters.format_rss(start_rss_megabytes or 0)} start"
            f" → {Formatters.format_rss(peak_rss_megabytes)} peak"
            f" → {Formatters.format_rss(end_rss_megabytes or 0)} end"
        )

    def _write_client_rss_trajectory(self, lines: List[str]) -> None:
        """
        Write client RSS start/peak/end if available.

        :param lines: Summary lines, appended to in place
        """
        start_rss_megabytes: Optional[float] = None
        end_rss_megabytes: Optional[float] = None
        peak_rss_megabytes: Optional[float] = None
        summary: Dict[str, Any]
        # Track the first, last and peak client RSS over the stages.
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
        # The arrow "→" leads from start to peak to end; plain "->" would change the summary text.
        lines.append(
            f"  Client RSS: {Formatters.format_rss(start_rss_megabytes or 0)} start"
            f" → {Formatters.format_rss(peak_rss_megabytes)} peak"
            f" → {Formatters.format_rss(end_rss_megabytes or 0)} end"
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
        summary: Dict[str, Any]
        # Track the first, last and peak system memory over the stages.
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
        total_gigabytes: float = SystemResources.total_gigabytes()
        # Show a missing start, end or free value as 0.
        if start_memory_percentage is None:
            start_memory_percentage = 0.0
        if end_memory_percentage is None:
            end_memory_percentage = 0.0
        if peak_available_gigabytes is None:
            peak_available_gigabytes = 0.0
        peak_detail: str = (
            f"{peak_memory_percentage:.0f}% peak ({peak_available_gigabytes:.1f} GB free / {total_gigabytes:.1f} GB)"
        )
        # The arrow "→" leads from start to peak to end; plain "->" would change the summary text.
        lines.append(
            f"  System memory: {start_memory_percentage:.0f}% start → {peak_detail}"
            f" → {end_memory_percentage:.0f}% end"
        )

    def _write_validation_summary(self, lines: List[str]) -> None:
        """
        Write validation retry summary if any events exist.

        :param lines: Summary lines, appended to in place
        """
        all_events: List[Dict[str, Any]] = []
        total_requests: int = 0
        summary: Dict[str, Any]
        # Collect the validation events and add up the requests of every stage.
        for summary in self._summaries:
            all_events.extend(summary.get("validation_events", []))
            total_requests += summary.get("concurrent", 0)
        if not all_events:
            return
        total_cycles: int = 0
        all_errors: List[str] = []
        event: Dict[str, Any]
        # Add up the fix cycles and collect the errors of every validation event.
        for event in all_events:
            total_cycles += event.get("fix_cycles", 0)
            all_errors.extend(event.get("errors", []))
        affected: int = len(all_events)
        lines.append(
            f"  Validation: {affected} of {total_requests} requests needed fixes ({total_cycles} fix cycles total)"
        )
        self._write_validation_time_impact(lines, all_events)
        if all_errors:
            counts: Counter = Counter(all_errors)
            top: List[Tuple[str, int]] = counts.most_common(3)
            parts: List[str] = []
            error: str
            count: int
            # One "error (Nx)" part per top error.
            for error, count in top:
                parts.append(f"{error} ({count}x)")
            top_errors_text: str = ", ".join(parts)
            lines.append(f"    {len(all_errors)} errors found: {top_errors_text}")

    def _write_validation_time_impact(self, lines: List[str], events: List[Dict[str, Any]]) -> None:
        """
        Write avg duration with/without validation fixes.

        :param lines: Summary lines, appended to in place
        :param events: Validation events from every stage
        """
        fix_request_ids: Set[str] = set()
        event: Dict[str, Any]
        # Collect the request id of each validation event.
        for event in events:
            fix_request_ids.add(event.get("request_id"))
        durations_with_fixes_seconds: List[float] = []
        durations_without_fixes_seconds: List[float] = []
        summary: Dict[str, Any]
        result: Dict[str, Any]
        # Split the request durations into requests with and without fixes.
        for summary in self._summaries:
            # One duration per request of the stage.
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
        summary: Dict[str, Any]
        # Gather the results of every stage.
        for summary in self._summaries:
            all_results.extend(summary.get("results", []))
        if not all_results:
            return

        lines.append(Formatters.SEPARATOR_LINE)
        lines.append("  REQUEST RESULTS")
        lines.append(Formatters.SEPARATOR_LINE)

        result: Dict[str, Any]
        # One line per request result.
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
        passed: int = 0
        latencies_seconds: List[float] = []
        result: Dict[str, Any]
        # Count the passed requests and collect each request's duration.
        for result in all_results:
            if result.get("status") == LoadTestConstants.STATUS_CREATED:
                passed += 1
            latencies_seconds.append(result.get("elapsed", 0))
        total: int = len(all_results)
        failed: int = total - passed
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
        summary: Dict[str, Any]
        # Collect the elapsed time of every request.
        for summary in self._summaries:
            result: Dict[str, Any]
            # One latency per request of the stage.
            for result in summary.get("results", []):
                all_latencies_seconds.append(result.get("elapsed", 0))
        if not all_latencies_seconds:
            return

        all_latencies_seconds.sort()
        total: int = len(all_latencies_seconds)
        milestones: List[int] = [50, 60, 70, 80, 90, 95, 100]
        lines.append(Formatters.SEPARATOR_LINE)
        lines.append("  COMPLETION TIMELINE")
        lines.append(Formatters.SEPARATOR_LINE)

        previous_count: int = -1
        percentage: int
        # One line per percentage milestone, skipping repeated counts.
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
        milestones: List[int] = LatencyAnalyzer.count_milestones(total)
        if not milestones:
            return
        lines.append("")
        lines.append("  Completion by count:")
        count: int
        # One line per count milestone.
        for count in milestones:
            duration_seconds: float = sorted_latencies_seconds[count - 1]
            formatted_duration: str = Formatters.fmt_duration(duration_seconds, precision=1)
            lines.append(f"  {count:5d} requests completed by {formatted_duration}")

    def _write_server_timing(self, lines: List[str]) -> None:
        """
        Write per-request server timing breakdown.

        :param lines: Summary lines, appended to in place
        """
        if not self._server_timing:
            return

        client_results: List[Dict[str, Any]] = self._collect_client_times()
        by_server_id: Dict[str, List[Dict[str, Any]]] = {}
        entry: Dict[str, Any]
        # Group the timing entries by server request id.
        for entry in self._server_timing:
            entry_request_id: str = entry.get("request_id", "")
            request_entries: List[Dict[str, Any]] = by_server_id.setdefault(entry_request_id, [])
            request_entries.append(entry)

        lines.append(Formatters.SEPARATOR_LINE)
        lines.append("  SERVER TIMING BREAKDOWN")
        lines.append(Formatters.SEPARATOR_LINE)

        server_request_id: str
        # One timing block per server request, in id order.
        for server_request_id in sorted(by_server_id.keys()):
            entries: List[Dict[str, Any]] = by_server_id.get(server_request_id)
            entries.sort(key=self._start_ts_of)
            if not entries:
                continue
            top_start_seconds: float = entries[0].get("start_ts", 0)
            client: Dict[str, Any] = self._match_client(top_start_seconds, client_results)
            label: str = client.get("id", server_request_id)
            self._format_request_timing(lines, label, entries, client)
        lines.append("")

    @staticmethod
    def _start_ts_of(timing_entry: Dict[str, Any]) -> float:
        """
        Sort key: the start time of a server timing entry.

        :param timing_entry: One server timing entry
        :return: The entry's "start_ts", 0 if missing
        """
        return timing_entry.get("start_ts", 0)

    def _collect_client_times(self) -> List[Dict[str, Any]]:
        """
        Collect client start/end times from all results.

        :return: id, start and end of each result that has both times
        """
        results: List[Dict[str, Any]] = []
        summary: Dict[str, Any]
        # Collect the start and end time of every timed request.
        for summary in self._summaries:
            result: Dict[str, Any]
            # Keep the requests that have an id and both times.
            for result in summary.get("results", []):
                request_id: str = result.get("request_id", "")
                start_time_seconds: float = result.get("start_time", 0)
                end_time_seconds: float = result.get("end_time", 0)
                if (request_id
                        and start_time_seconds
                        and end_time_seconds):
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
        client: Dict[str, Any]
        # Return the first client request whose time span holds the server start time.
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
        total_duration_seconds: float = 0
        if client_start_seconds and client_end_seconds:
            total_duration_seconds = client_end_seconds - client_start_seconds
        server_start_seconds: float = top.get("start_ts", 0)
        server_finish_seconds: float = top.get("finish_ts", 0)
        lines.append("")
        lines.append(f"  {request_id} ({total_duration_seconds:.1f}s total):")
        if (client_start_seconds
                and server_start_seconds
                and server_start_seconds > client_start_seconds):
            lines.append(f"    Client -> Server:  {server_start_seconds - client_start_seconds:6.1f}s")
        top_duration_seconds: float = top.get("duration_seconds", 0)
        lines.append(f"    Server: {top_agent:<25s} {top_duration_seconds:6.1f}s")
        SummaryFileWriter._format_sub_agents(lines, entries, top_agent)
        if (client_end_seconds
                and server_finish_seconds
                and client_end_seconds > server_finish_seconds):
            lines.append(f"    Server -> Client:  {client_end_seconds - server_finish_seconds:6.1f}s")

    @staticmethod
    def _format_sub_agents(lines: List[str], entries: List[Dict[str, Any]], top_agent: str) -> None:
        """
        Format sub-agent timing lines.

        :param lines: Summary lines, appended to in place
        :param entries: Server timing entries of the request
        :param top_agent: Name of the top-level agent, left out of the list
        """
        sub_agents: List[Dict[str, Any]] = []
        timing_entry: Dict[str, Any]
        # Keep every agent except the top-level one.
        for timing_entry in entries:
            if timing_entry.get("agent") != top_agent:
                sub_agents.append(timing_entry)
        index: int
        sub_agent: Dict[str, Any]
        # One tree line per sub-agent.
        for index, sub_agent in enumerate(sub_agents):
            # Box-drawing "└─" marks the last sub-agent and "├─" the others; ASCII "+-" would change the summary text.
            prefix: str = "├─"
            if index == len(sub_agents) - 1:
                prefix = "└─"
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
        key: str
        # Use the first detail field that has a value.
        for key in ["agent_network_name", "reservation_id"]:
            value: Optional[str] = result.get(key, "")
            if value:
                parts.append(str(value))
                break
        reason: Optional[str] = result.get("failure_reason")
        if reason:
            parts.append(f"reason: {reason}")
        return "  ".join(parts)
