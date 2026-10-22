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
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple

from collections import Counter

from tests.load_tests.load_test_constants import STATUS_CREATED
from tests.load_tests.load_test_constants import STATUS_FAILED
from tests.load_tests.load_test_constants import STATUS_KILLED
from tests.load_tests.load_test_constants import STATUS_TIMEOUT
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.system_resources import SysSnapshot
from tests.load_tests.reporting.system_resources import SystemResources
from tests.load_tests.reporting.table_formatter import TableFormatter

logger: logging.Logger = logging.getLogger(__name__)


class SummaryReporter:
    """
    Logs ramp-up and overall results across all stages.

    Holds the collected stage summaries so that multiple
    reporting methods can access them without re-passing.
    """

    def __init__(self, stage_summaries: List[Dict[str, Any]], neuro_san_version: Optional[str] = None,
                 client_token_source: str = "HTTP token_accounting") -> None:
        """
        Constructor.

        :param stage_summaries: Per-stage summaries collected during the run
        :param neuro_san_version: Installed neuro-san version, or None when unknown
        :param client_token_source: Where the client token counts came from, shown in the token usage block
        """
        self._summaries: List[Dict[str, Any]] = stage_summaries
        self._neuro_san_version: Optional[str] = neuro_san_version
        self._client_token_source: str = client_token_source

    def log_ramp_summary(self, is_ramp: bool = True) -> None:
        """
        Log the ramp-up summary table across all stages.

        :param is_ramp: True to label each row by stage, False by round
        """
        logger.info("\n%s", Formatters.SEPARATOR_LINE)
        title: str = "ROUND SUMMARY"
        if is_ramp:
            title = "RAMP-UP SUMMARY"
        logger.info("  %s", title)
        logger.info("%s", Formatters.SEPARATOR_LINE)

        has_server_counts: bool = False
        summary: Dict[str, Any]
        # Look for a stage that has server-side request counts.
        for summary in self._summaries:
            if summary.get("primary_started") is not None:
                has_server_counts = True
                break
        first_col: str = "Round"
        if is_ramp:
            first_col = "Stage"
        header: List[str] = [
            first_col, "Concurrent", "Created", "Failed",
            "Timeout", "Killed", "Retries", "Amplification",
            "Duration",
        ]
        if has_server_counts:
            header.extend(["Recv", "Done", "Internal"])
        rows: List[List[str]] = []
        # One table row per stage.
        for summary in self._summaries:
            row_label: Any = summary.get("stage")
            if not is_ramp:
                row_label = summary.get("round", row_label)
            row: List[str] = [str(row_label)]
            stage_cells: List[str] = SummaryReporter._stage_cells(summary)
            row.extend(stage_cells)
            if has_server_counts:
                server_cells: List[str] = SummaryReporter._server_count_cells(summary)
                row.extend(server_cells)
            rows.append(row)
        TableFormatter.log_table(header, rows)

    def log_overall_results(self) -> None:
        """
        Log overall results across all stages.
        """
        total_created: int = 0
        total_failed: int = 0
        total_timeout: int = 0
        total_killed: int = 0
        total_time_seconds: float = 0.0
        total_retries: int = 0

        summary: Dict[str, Any]
        # Add up the status counts, time and retries of every stage.
        for summary in self._summaries:
            counts: Dict[str, int] = summary.get("counts", {})
            total_created += counts.get(STATUS_CREATED, 0)
            total_failed += counts.get(STATUS_FAILED, 0)
            total_timeout += counts.get(STATUS_TIMEOUT, 0)
            total_killed += counts.get(STATUS_KILLED, 0)
            total_time_seconds += summary.get("elapsed", 0)
            total_retries += summary.get("total_retries", 0)

        total_sent: int = total_created + total_failed + total_timeout + total_killed

        logger.info("\n%s", Formatters.SEPARATOR_LINE)
        logger.info("  OVERALL RESULTS")
        logger.info("%s", Formatters.SEPARATOR_LINE)
        if self._neuro_san_version:
            logger.info("  neuro-san version: %s", self._neuro_san_version)
        logger.info("  Total requests: %s", total_sent)
        logger.info("    Created:   %s", total_created)
        logger.info("    Failed:    %s", total_failed)
        logger.info("    Timed out: %s", total_timeout)
        logger.info("    Killed:    %s", total_killed)
        total_time_text: str = Formatters.fmt_duration(total_time_seconds, precision=2)
        logger.info("  Total wall time: %s", total_time_text)
        self._log_performance_stats()

        if total_retries > 0:
            total_requests: int = 0
            stage_summary: Dict[str, Any]
            # Add up the requests of every stage.
            for stage_summary in self._summaries:
                total_requests += stage_summary.get("concurrent", 0)
            amplification: float = 1.0
            if total_requests > 0:
                amplification = (total_requests + total_retries) / total_requests
            logger.info("\n  Overall retry totals:")
            logger.info("    Total retries:   %s", total_retries)
            logger.info("    Amplification:   %.2fx", amplification)

        self._log_llm_token_usage()
        self._log_system_resources()

    @staticmethod
    def render_token_usage(client: Optional[Dict[str, int]], server: Optional[Dict[str, int]],
                           client_source: str) -> bool:
        """
        Render the LLM & TOKEN USAGE block; return True if printed.

        ``client`` and ``server`` are token-stat dicts (from
        ``aggregate_token_entries``) or None when that side is
        unavailable.  Prints nothing when both are None.

        :param client: Client token stats, or None
        :param server: Server log token stats, or None
        :param client_source: Where the client token counts came from
        :return: True if the block was logged, False when both are None
        """
        if client is None and server is None:
            return False
        logger.info("\n%s", Formatters.SEPARATOR_LINE)
        logger.info("  LLM & TOKEN USAGE")
        logger.info("%s", Formatters.SEPARATOR_LINE)
        SummaryReporter._log_token_source(f"Client ({client_source})", client)
        SummaryReporter._log_token_source("Server log", server)
        if client is not None and server is not None:
            SummaryReporter._log_token_match(client, server)
        return True

    @staticmethod
    def aggregate_token_entries(entries: Iterable[Dict[str, Any]]) -> Optional[Dict[str, int]]:
        """
        Aggregate token dicts into a stats dict, or None if empty.

        Each entry needs total_tokens, prompt_tokens,
        completion_tokens, and llm_calls.  Entries with zero total
        tokens are ignored.

        :param entries: Per-request token dicts
        :return: calls_* and tok_* min/avg/max/total, prompt_total and comp_total; None when no entry has tokens
        """
        calls: List[int] = []
        token_counts: List[int] = []
        prompt_total: int = 0
        completion_total: int = 0
        entry: Dict[str, Any]
        # Add up the token fields of each entry that has tokens.
        for entry in entries:
            token_count: int = entry.get("total_tokens", 0) or 0
            if not token_count:
                continue
            token_counts.append(token_count)
            prompt_total += entry.get("prompt_tokens", 0) or 0
            completion_total += entry.get("completion_tokens", 0) or 0
            calls.append(entry.get("llm_calls", 0) or 0)
        if not token_counts:
            return None
        count: int = len(token_counts)
        return {
            "calls_min": min(calls),
            "calls_avg": round(sum(calls) / count),
            "calls_max": max(calls),
            "calls_total": sum(calls),
            "tok_min": min(token_counts),
            "tok_avg": round(sum(token_counts) / count),
            "tok_max": max(token_counts),
            "tok_total": sum(token_counts),
            "prompt_total": prompt_total,
            "comp_total": completion_total,
        }

    def _log_performance_stats(self) -> None:
        """
        Log time-to-first-response and request-duration stats.
        """
        first_response_stats: Optional[Dict[str, float]] = self._time_to_first_response_stats()
        if first_response_stats is not None:
            logger.info(
                "  Time to first response: %s min / %s avg / %s max",
                Formatters.fmt_duration(first_response_stats.get("min_seconds", 0)),
                Formatters.fmt_duration(first_response_stats.get("avg_seconds", 0)),
                Formatters.fmt_duration(first_response_stats.get("max_seconds", 0)),
            )

        request_duration_stats: Optional[Dict[str, float]] = self._request_duration_stats()
        if request_duration_stats is not None:
            logger.info(
                "  Request duration: %s min / %s avg / %s max",
                Formatters.fmt_duration(request_duration_stats.get("min_seconds", 0)),
                Formatters.fmt_duration(request_duration_stats.get("avg_seconds", 0)),
                Formatters.fmt_duration(request_duration_stats.get("max_seconds", 0)),
            )

        self._log_validation_summary()

    def _log_llm_token_usage(self) -> None:
        """
        Log the LLM & TOKEN USAGE section (client vs server log).

        A uniform block for all modes: the client side comes from
        HTTP token accounting, the server side from
        server.log.  Whichever side is unavailable prints "not
        available".  When both are present (all-in-one) a Match line
        reports whether they agree.
        """
        client: Optional[Dict[str, int]] = None
        server: Optional[Dict[str, int]] = None
        if self._has_client_token_copy():
            client = self._token_stats("client_")
            server = self._token_stats("")
        else:
            client = self._token_stats("")
            server = None
        printed: bool = SummaryReporter.render_token_usage(client, server, client_source=self._client_token_source)
        if printed:
            self._log_model_distribution()

    @staticmethod
    def _log_token_source(label: str, stats: Optional[Dict[str, int]]) -> None:
        """
        Log one source's LLM/token lines, or 'not available'.

        :param label: Source name shown before its lines
        :param stats: Token stats from aggregate_token_entries, or None
        """
        if stats is None:
            logger.info("  %s: not available", label)
            return
        logger.info("  %s:", label)
        logger.info(
            "    LLM calls: %s total  (%s / %s / %s min/avg/max)",
            stats.get("calls_total", 0), stats.get("calls_min", 0),
            stats.get("calls_avg", 0), stats.get("calls_max", 0),
        )
        logger.info(
            "    Tokens:    %s total  (%s / %s / %s min/avg/max),  %s prompt + %s completion",
            f"{stats.get("tok_total", 0):,}", f"{stats.get("tok_min", 0):,}",
            f"{stats.get("tok_avg", 0):,}", f"{stats.get("tok_max", 0):,}",
            f"{stats.get("prompt_total", 0):,}", f"{stats.get("comp_total", 0):,}",
        )

    @staticmethod
    def _log_token_match(client: Dict[str, int], server: Dict[str, int]) -> None:
        """
        Log whether client and server-log totals agree.

        :param client: Client token stats
        :param server: Server log token stats
        """
        calls_match: bool = client.get("calls_total", 0) == server.get("calls_total", 0)
        tokens_match: bool = client.get("tok_total", 0) == server.get("tok_total", 0)
        if calls_match and tokens_match:
            logger.info("  Match: OK")
            return
        logger.info(
            "  Match: MISMATCH — LLM calls %s vs %s, tokens %s vs %s",
            client.get("calls_total", 0), server.get("calls_total", 0),
            f"{client.get("tok_total", 0):,}", f"{server.get("tok_total", 0):,}",
        )

    def _has_client_token_copy(self) -> bool:
        """
        True if results carry a preserved client-side token copy.

        :return: True if any result has client_total_tokens
        """
        summary: Dict[str, Any]
        # Look for any result that carries a client token copy.
        for summary in self._summaries:
            result: Dict[str, Any]
            # Stop at the first result with client tokens.
            for result in summary.get("results", []):
                if "client_total_tokens" in result:
                    return True
        return False

    def _token_stats(self, prefix: str) -> Optional[Dict[str, int]]:
        """
        Aggregate per-request token fields (optionally prefixed).

        :param prefix: Prefix on the token field names: "client_", or "" for none
        :return: Token stats from aggregate_token_entries, or None when no result has tokens
        """
        entries: List[Dict[str, Any]] = []
        summary: Dict[str, Any]
        # One token entry per request of every stage.
        for summary in self._summaries:
            result: Dict[str, Any]
            # Read the token fields with the given prefix.
            for result in summary.get("results", []):
                entries.append({
                    "total_tokens": result.get(
                        prefix + "total_tokens", 0,
                    ),
                    "prompt_tokens": result.get(
                        prefix + "prompt_tokens", 0,
                    ),
                    "completion_tokens": result.get(
                        prefix + "completion_tokens", 0,
                    ),
                    "llm_calls": result.get(
                        prefix + "llm_calls", 0,
                    ),
                })
        return SummaryReporter.aggregate_token_entries(entries)

    def _log_system_resources(self) -> None:
        """
        Log the aligned SYSTEM RESOURCES before/peak/after section.
        """
        SystemResources.log_section(
            self._sys_edge_snapshot("before"),
            self._sys_peak_snapshot(),
            self._sys_edge_snapshot("after"),
        )

    def _sys_edge_snapshot(self, edge: str) -> Optional[SysSnapshot]:
        """
        Build the before/after whole-system snapshot across stages.

        ``before`` takes the first stage's start values; ``after``
        takes the last stage's end values.  Returns None when no
        system data was collected.

        :param edge: "before" or "after"
        :return: The snapshot, or None when no stage has system data
        """
        prefix: str = f"{edge}_sys_"
        chosen_snapshot: Optional[SysSnapshot] = None
        summary: Dict[str, Any]
        # Find the first ("before") or last ("after") stage with system data.
        for summary in self._summaries:
            memory_percentage: Optional[float] = summary.get(prefix + "mem_pct")
            if memory_percentage is None:
                continue
            snapshot: SysSnapshot = {
                "mem_pct": memory_percentage,
                "mem_avail_gb": summary.get(prefix + "mem_avail_gb"),
                "cpu_pct": summary.get(prefix + "cpu"),
                "threads": summary.get(prefix + "threads"),
            }
            if edge == "before":
                return snapshot
            chosen_snapshot = snapshot
        return chosen_snapshot

    def _sys_peak_snapshot(self) -> Optional[SysSnapshot]:
        """
        Build the whole-system peak snapshot (per-metric max).

        :return: Highest value of each metric across stages, or None when no stage has peak data
        """
        peak_memory_percentage: Optional[float] = None
        peak_available_gigabytes: Optional[float] = None
        peak_cpu_percentage: Optional[float] = None
        peak_threads: Optional[int] = None
        summary: Dict[str, Any]
        # Keep the largest value of each system metric.
        for summary in self._summaries:
            memory_percentage: Optional[float] = summary.get("peak_sys_mem_pct")
            if (memory_percentage is not None
                    and (peak_memory_percentage is None
                         or memory_percentage > peak_memory_percentage)):
                peak_memory_percentage = memory_percentage
                peak_available_gigabytes = summary.get("peak_sys_mem_avail_gb")
            cpu_percentage: Optional[float] = summary.get("peak_sys_cpu")
            if (cpu_percentage is not None
                    and (peak_cpu_percentage is None
                         or cpu_percentage > peak_cpu_percentage)):
                peak_cpu_percentage = cpu_percentage
            threads: Optional[int] = summary.get("peak_sys_threads")
            if (threads is not None
                    and (peak_threads is None
                         or threads > peak_threads)):
                peak_threads = threads
        if (peak_memory_percentage is None
                and peak_cpu_percentage is None
                and peak_threads is None):
            return None
        return {
            "mem_pct": peak_memory_percentage,
            "mem_avail_gb": peak_available_gigabytes,
            "cpu_pct": peak_cpu_percentage,
            "threads": peak_threads,
        }

    def _request_duration_stats(self) -> Optional[Dict[str, float]]:
        """
        Compute min/avg/max elapsed time across requests.

        :return: "min_seconds", "avg_seconds" and "max_seconds" of the elapsed time; None when there are no results
        """
        durations_seconds: List[float] = []
        summary: Dict[str, Any]
        # Collect the elapsed time of every request.
        for summary in self._summaries:
            result: Dict[str, Any]
            # One duration per request of the stage.
            for result in summary.get("results", []):
                durations_seconds.append(result.get("elapsed", 0))
        if not durations_seconds:
            return None
        return {
            "min_seconds": min(durations_seconds),
            "avg_seconds": sum(durations_seconds) / len(durations_seconds),
            "max_seconds": max(durations_seconds),
        }

    def _log_model_distribution(self) -> None:
        """
        Log LLM model usage and flag fallback models.

        Collects model names from all results and reports
        how many requests used each model.  When multiple
        models appear, highlights the non-primary ones as
        potential fallbacks.
        """
        model_counts: Counter = Counter()
        fallback_requests: int = 0
        summary: Dict[str, Any]
        result: Dict[str, Any]
        model_name: str
        # Count the models of every request in every stage.
        for summary in self._summaries:
            # Count the models each request of the stage used.
            for result in summary.get("results", []):
                all_models: List[str] = result.get("all_models", [])
                model: Optional[str] = result.get("model")
                if all_models:
                    # Count every model the request used, fallbacks included.
                    for model_name in all_models:
                        model_counts[model_name] = model_counts.get(model_name, 0) + 1
                    if len(all_models) > 1:
                        fallback_requests += 1
                elif model and model != "unknown":
                    model_counts[model] = model_counts.get(model, 0) + 1
        if not model_counts:
            return
        model_parts: List[str] = []
        count: int
        # One "model (N)" part per model, most used first.
        for model_name, count in model_counts.most_common():
            model_parts.append(f"{model_name} ({count})")
        logger.info("  LLM models: %s", ", ".join(model_parts))
        if fallback_requests > 0:
            logger.info("    Fallback LLM used: %s request(s)", fallback_requests)

    def _time_to_first_response_stats(self) -> Optional[Dict[str, float]]:
        """
        Compute min/avg/max time-to-first-response.

        :return: Dictionary with "min_seconds", "avg_seconds" and "max_seconds" over the
                 requests that received a first response; None when none did
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
        if not first_response_seconds:
            return None
        return {
            "min_seconds": min(first_response_seconds),
            "avg_seconds": sum(first_response_seconds) / len(first_response_seconds),
            "max_seconds": max(first_response_seconds),
        }

    def _log_validation_summary(self) -> None:
        """
        Log aggregate validation retry info if any.
        """
        all_events: List[Dict[str, Any]] = self._collect_validation_events()
        if not all_events:
            return
        total_requests: int = 0
        stage_summary: Dict[str, Any]
        # Add up the requests of every stage.
        for stage_summary in self._summaries:
            total_requests += stage_summary.get("concurrent", 0)
        affected: int = len(all_events)
        total_cycles: int = 0
        all_errors: List[str] = []
        event: Dict[str, Any]
        # Add up the fix cycles and collect the errors of every validation event.
        for event in all_events:
            total_cycles += event.get("fix_cycles", 0)
            all_errors.extend(event.get("errors", []))
        logger.info(
            "\n  Validation: %s of %s requests needed fixes (%s fix cycles total)",
            affected, total_requests, total_cycles,
        )
        self._log_validation_time_impact(all_events)
        if all_errors:
            self._log_top_errors(all_errors)

    def _log_validation_time_impact(self, events: List[Dict[str, Any]]) -> None:
        """
        Log avg duration of requests with/without fixes.

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
            logger.info(
                "    Requests with fixes took %s avg vs %s avg without",
                Formatters.fmt_duration(average_with_fixes_seconds),
                Formatters.fmt_duration(average_without_fixes_seconds),
            )

    @staticmethod
    def _log_top_errors(all_errors: List[str]) -> None:
        """
        Log the most common validation errors.

        :param all_errors: Every validation error, repeats included
        """
        counts: Counter = Counter(all_errors)
        top: List[Tuple[str, int]] = counts.most_common(3)
        parts: List[str] = []
        error: str
        count: int
        # One "error (Nx)" part per top error.
        for error, count in top:
            parts.append(f"{error} ({count}x)")
        logger.info("    %s errors found: %s", len(all_errors), ", ".join(parts))

    def _collect_validation_events(self) -> List[Dict[str, Any]]:
        """
        Gather all validation events across stages.

        :return: Validation events from every stage, in stage order
        """
        events: List[Dict[str, Any]] = []
        summary: Dict[str, Any]
        # Gather the validation events of every stage.
        for summary in self._summaries:
            events.extend(summary.get("validation_events", []))
        return events

    @staticmethod
    def _stage_cells(summary: Dict[str, Any]) -> List[str]:
        """
        Build the cells from Workers to Duration of one summary table row.

        :param summary: One stage or round summary
        :return: Workers, the 4 status counts, retries, amplification and duration
        """
        counts: Dict[str, int] = summary.get("counts", {})
        concurrent: Optional[int] = summary.get("concurrent")
        created_count: int = counts.get(STATUS_CREATED, 0)
        failed_count: int = counts.get(STATUS_FAILED, 0)
        timeout_count: int = counts.get(STATUS_TIMEOUT, 0)
        killed_count: int = counts.get(STATUS_KILLED, 0)
        total_retries: int = summary.get("total_retries", 0)
        amplification: float = summary.get("amplification", 1.0)
        elapsed_seconds: float = summary.get("elapsed", 0)
        cells: List[str] = [
            str(concurrent),
            str(created_count),
            str(failed_count),
            str(timeout_count),
            str(killed_count),
            str(total_retries),
            f"{amplification:.2f}x",
            f"{elapsed_seconds:.1f}s",
        ]
        return cells

    @staticmethod
    def _server_count_cells(summary: Dict[str, Any]) -> List[str]:
        """
        Build the Recv, Done and Internal cells of one summary table row.

        :param summary: One stage or round summary
        :return: Primary requests started, primary requests finished and internal calls, "-" when a count is missing
        """
        primary_started: Optional[int] = summary.get("primary_started")
        primary_finished: Optional[int] = summary.get("primary_finished")
        total_started: Optional[int] = summary.get("total_started")
        primary_started_text: str = "-"
        if primary_started is not None:
            primary_started_text = str(primary_started)
        primary_finished_text: str = "-"
        if primary_finished is not None:
            primary_finished_text = str(primary_finished)
        internal: str = "-"
        if primary_started is not None and total_started is not None:
            internal = str(total_started - primary_started)
        cells: List[str] = [primary_started_text, primary_finished_text, internal]
        return cells
