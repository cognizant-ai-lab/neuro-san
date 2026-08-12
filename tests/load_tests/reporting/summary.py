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

"""Summary reporting — ramp-up and overall results."""

import logging

from collections import Counter

from tests.load_tests.config import Formatters
from tests.load_tests.config import SEPARATOR_WIDTH
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.reporting.system_resources import SystemResources
from tests.load_tests.reporting.table_formatter import TableFormatter

logger = logging.getLogger(__name__)


class SummaryReporter:
    """Logs ramp-up and overall results across all stages.

    Holds the collected stage summaries so that multiple
    reporting methods can access them without re-passing.
    """

    def __init__(self, stage_summaries, neuro_san_version=None,
                 client_token_source="agent_cli --tokens") -> None:
        self._summaries = stage_summaries
        self._neuro_san_version = neuro_san_version
        self._client_token_source = client_token_source

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
        if self._neuro_san_version:
            logger.info(
                "  neuro-san version: %s", self._neuro_san_version,
            )
        logger.info("  Total requests: %s", total_sent)
        logger.info("    Created:   %s", total_created)
        logger.info("    Failed:    %s", total_failed)
        logger.info("    Timed out: %s", total_timeout)
        logger.info("    Killed:    %s", total_killed)
        logger.info(
            "  Total wall time: %s",
            Formatters.fmt_duration(total_time, precision=2),
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
            logger.info("\n  Overall retry totals:")
            logger.info("    Total retries:   %s", total_retries)
            logger.info(
                "    Amplification:   %.2fx", amplification,
            )

        self._log_llm_token_usage()
        self._log_system_resources()

    def _log_performance_stats(self) -> None:
        """Log TTFR and request-duration stats."""
        ttfr = self._ttfr_stats()
        if ttfr is not None:
            logger.info(
                "  Time to first response: %s min"
                " / %s avg / %s max",
                Formatters.fmt_duration(ttfr.get("min", 0)),
                Formatters.fmt_duration(ttfr.get("avg", 0)),
                Formatters.fmt_duration(ttfr.get("max", 0)),
            )

        duration = self._request_duration_stats()
        if duration is not None:
            logger.info(
                "  Request duration: %s min / %s avg"
                " / %s max",
                Formatters.fmt_duration(duration.get("min", 0)),
                Formatters.fmt_duration(duration.get("avg", 0)),
                Formatters.fmt_duration(duration.get("max", 0)),
            )

        self._log_validation_summary()

    def _log_llm_token_usage(self) -> None:
        """Log the LLM & TOKEN USAGE section (client vs server log).

        A uniform block for all modes: the client side comes from
        agent_cli/HTTP token accounting, the server side from
        server.log.  Whichever side is unavailable prints "not
        available".  When both are present (all-in-one) a Match line
        reports whether they agree.
        """
        if self._has_client_token_copy():
            client = self._token_stats("client_")
            server = self._token_stats("")
        else:
            client = self._token_stats("")
            server = None
        printed = SummaryReporter.render_token_usage(
            client, server,
            client_source=self._client_token_source,
        )
        if printed:
            self._log_model_distribution()

    @staticmethod
    def render_token_usage(client, server, *, client_source) -> bool:
        """Render the LLM & TOKEN USAGE block; return True if printed.

        ``client`` and ``server`` are token-stat dicts (from
        ``aggregate_token_entries``) or None when that side is
        unavailable.  Prints nothing when both are None.
        """
        if client is None and server is None:
            return False
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  LLM & TOKEN USAGE")
        logger.info("=" * SEPARATOR_WIDTH)
        SummaryReporter._log_token_source(
            f"Client ({client_source})", client,
        )
        SummaryReporter._log_token_source("Server log", server)
        if client is not None and server is not None:
            SummaryReporter._log_token_match(client, server)
        return True

    @staticmethod
    def _log_token_source(label, stats) -> None:
        """Log one source's LLM/token lines, or 'not available'."""
        if stats is None:
            logger.info("  %s: not available", label)
            return
        logger.info("  %s:", label)
        logger.info(
            "    LLM calls: %s total  (%s / %s / %s min/avg/max)",
            stats["calls_total"], stats["calls_min"],
            stats["calls_avg"], stats["calls_max"],
        )
        logger.info(
            "    Tokens:    %s total  (%s / %s / %s min/avg/max),"
            "  %s prompt + %s completion",
            f"{stats['tok_total']:,}", f"{stats['tok_min']:,}",
            f"{stats['tok_avg']:,}", f"{stats['tok_max']:,}",
            f"{stats['prompt_total']:,}", f"{stats['comp_total']:,}",
        )

    @staticmethod
    def _log_token_match(client, server) -> None:
        """Log whether client and server-log totals agree."""
        calls_ok = client["calls_total"] == server["calls_total"]
        tok_ok = client["tok_total"] == server["tok_total"]
        if calls_ok and tok_ok:
            logger.info("  Match: OK")
            return
        logger.info(
            "  Match: MISMATCH — LLM calls %s vs %s, "
            "tokens %s vs %s",
            client["calls_total"], server["calls_total"],
            f"{client['tok_total']:,}", f"{server['tok_total']:,}",
        )

    @staticmethod
    def aggregate_token_entries(entries):
        """Aggregate token dicts into a stats dict, or None if empty.

        Each entry needs total_tokens, prompt_tokens,
        completion_tokens, and llm_calls.  Entries with zero total
        tokens are ignored.
        """
        calls = []
        toks = []
        prompt_total = 0
        comp_total = 0
        for entry in entries:
            tok = entry.get("total_tokens", 0) or 0
            if not tok:
                continue
            toks.append(tok)
            prompt_total += entry.get("prompt_tokens", 0) or 0
            comp_total += entry.get("completion_tokens", 0) or 0
            calls.append(entry.get("llm_calls", 0) or 0)
        if not toks:
            return None
        count = len(toks)
        return {
            "calls_min": min(calls),
            "calls_avg": round(sum(calls) / count),
            "calls_max": max(calls),
            "calls_total": sum(calls),
            "tok_min": min(toks),
            "tok_avg": round(sum(toks) / count),
            "tok_max": max(toks),
            "tok_total": sum(toks),
            "prompt_total": prompt_total,
            "comp_total": comp_total,
        }

    def _has_client_token_copy(self) -> bool:
        """True if results carry a preserved client-side token copy."""
        for summary in self._summaries:
            for result in summary.get("results", []):
                if "client_total_tokens" in result:
                    return True
        return False

    def _token_stats(self, prefix):
        """Aggregate per-request token fields (optionally prefixed)."""
        entries = []
        for summary in self._summaries:
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
        """Log the aligned SYSTEM RESOURCES before/peak/after section."""
        SystemResources.log_section(
            self._sys_edge_snapshot("before"),
            self._sys_peak_snapshot(),
            self._sys_edge_snapshot("after"),
        )

    def _sys_edge_snapshot(self, edge):
        """Build the before/after whole-system snapshot across stages.

        ``before`` takes the first stage's start values; ``after``
        takes the last stage's end values.  Returns None when no
        system data was collected.
        """
        prefix = f"{edge}_sys_"
        chosen = None
        for summary in self._summaries:
            pct = summary.get(prefix + "mem_pct")
            if pct is None:
                continue
            snap = {
                "mem_pct": pct,
                "mem_avail_gb": summary.get(prefix + "mem_avail_gb"),
                "cpu_pct": summary.get(prefix + "cpu"),
                "threads": summary.get(prefix + "threads"),
            }
            if edge == "before":
                return snap
            chosen = snap
        return chosen

    def _sys_peak_snapshot(self):
        """Build the whole-system peak snapshot (per-metric max)."""
        peak_pct = None
        peak_avail = None
        peak_cpu = None
        peak_threads = None
        for summary in self._summaries:
            pct = summary.get("peak_sys_mem_pct")
            if pct is not None and (peak_pct is None or pct > peak_pct):
                peak_pct = pct
                peak_avail = summary.get("peak_sys_mem_avail_gb")
            cpu = summary.get("peak_sys_cpu")
            if cpu is not None and (peak_cpu is None or cpu > peak_cpu):
                peak_cpu = cpu
            threads = summary.get("peak_sys_threads")
            if (threads is not None
                    and (peak_threads is None or threads > peak_threads)):
                peak_threads = threads
        if peak_pct is None and peak_cpu is None and peak_threads is None:
            return None
        return {
            "mem_pct": peak_pct,
            "mem_avail_gb": peak_avail,
            "cpu_pct": peak_cpu,
            "threads": peak_threads,
        }

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

    def _log_model_distribution(self) -> None:
        """Log LLM model usage and flag fallback models.

        Collects model names from all results and reports
        how many requests used each model.  When multiple
        models appear, highlights the non-primary ones as
        potential fallbacks.
        """
        model_counts: Counter = Counter()
        fallback_requests = 0
        for summary in self._summaries:
            for result in summary.get("results", []):
                all_models = result.get("all_models", [])
                model = result.get("model")
                if all_models:
                    for m in all_models:
                        model_counts[m] += 1
                    if len(all_models) > 1:
                        fallback_requests += 1
                elif model and model != "unknown":
                    model_counts[model] += 1
        if not model_counts:
            return
        logger.info(
            "  LLM models: %s",
            ", ".join(
                f"{m} ({c})" for m, c in
                model_counts.most_common()
            ),
        )
        if fallback_requests > 0:
            logger.info(
                "    Fallback LLM used: %s request(s)",
                fallback_requests,
            )

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
                Formatters.fmt_duration(avg_with),
                Formatters.fmt_duration(avg_without),
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
