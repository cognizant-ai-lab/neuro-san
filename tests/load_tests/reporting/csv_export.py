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

"""CSV export — per-request and per-stage resource data for analysis."""

import csv
import logging
import os
import time

from tests.load_tests.config import estimate_cost

logger = logging.getLogger(__name__)

# Fields that live on each result dict (not CSV-specific metadata)
_RESULT_META_KEYS = {
    "status", "elapsed", "prompt", "error", "request_id",
}


class CsvExporter:
    """Writes per-request and per-stage resource CSV files."""

    # ------------------------------------------------------------------
    # results_per_request.csv
    # ------------------------------------------------------------------

    # pylint: disable=too-many-locals
    @staticmethod
    def export_per_request_csv(output_dir, stage_summaries, agent_name):
        """Write per-request CSV with one row per request.

        Columns include: core fields, token accounting, cost,
        retry/disconnection data, and any agent-specific parsed fields.
        """
        if not output_dir:
            return

        csv_path = os.path.join(output_dir, "results_per_request.csv")
        run_id = time.strftime("%Y-%m-%d_%H%M")

        # Core columns always present
        fieldnames = [
            "run_id", "timestamp", "agent", "stage", "round",
            "request_id", "status", "duration_sec", "prompt",
            "error",
            "total_tokens", "prompt_tokens", "completion_tokens",
            "llm_calls", "model", "cost_usd",
            "total_retries", "client_disconnected",
        ]

        # Discover additional dynamic fields from results
        extra_keys = set()
        for summary in stage_summaries:
            for result in summary.get("results", []):
                for key in result:
                    if key not in _RESULT_META_KEYS and key not in {
                        "total_tokens", "prompt_tokens",
                        "completion_tokens", "llm_calls",
                        "model", "cost_usd",
                    }:
                        extra_keys.add(key)
        sorted_extras = sorted(extra_keys)
        fieldnames.extend(sorted_extras)

        disconnection_index = CsvExporter._build_disconnection_index(
            stage_summaries,
        )

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(csv_path, "w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            request_num = 0
            for summary in stage_summaries:
                stage = summary.get("stage", 0)
                round_num = summary.get("round", 1)
                has_log = summary.get("has_server_log", False)
                has_tok = summary.get("has_tokens", False)
                stage_retries = summary.get("total_retries", 0)
                stage_reqs = summary.get("concurrent", 0)
                retry_per_req = (
                    stage_retries / stage_reqs
                    if stage_reqs > 0 else 0
                )

                for result in summary.get("results", []):
                    request_num += 1
                    rid = result.get(
                        "request_id", f"request-{request_num}",
                    )
                    tok_measured = (
                        has_tok
                        or "total_tokens" in result
                    )
                    prompt_tok = result.get(
                        "prompt_tokens", 0 if tok_measured else "",
                    )
                    compl_tok = result.get(
                        "completion_tokens",
                        0 if tok_measured else "",
                    )
                    model = result.get(
                        "model",
                        "unknown" if tok_measured else "",
                    )
                    cost = result.get("cost_usd", "")
                    if (
                        cost == ""
                        and tok_measured
                    ):
                        cost = estimate_cost(
                            prompt_tok, compl_tok, model,
                        )

                    row = {
                        "run_id": run_id,
                        "timestamp": timestamp,
                        "agent": agent_name,
                        "stage": stage,
                        "round": round_num,
                        "request_id": rid,
                        "status": result.get("status", ""),
                        "duration_sec": (
                            f"{result.get('elapsed', 0):.2f}"
                        ),
                        "prompt": result.get("prompt", ""),
                        "error": result.get("error", ""),
                        "total_tokens": result.get(
                            "total_tokens",
                            0 if tok_measured else "",
                        ),
                        "prompt_tokens": prompt_tok,
                        "completion_tokens": compl_tok,
                        "llm_calls": result.get(
                            "llm_calls",
                            0 if tok_measured else "",
                        ),
                        "model": model,
                        "cost_usd": (
                            f"{cost:.6f}" if isinstance(cost, float)
                            else cost
                        ),
                        "total_retries": (
                            f"{retry_per_req:.1f}"
                            if has_log else ""
                        ),
                        "client_disconnected": (
                            "yes" if rid in disconnection_index
                            else ("no" if has_log else "")
                        ),
                    }
                    for field in sorted_extras:
                        row[field] = result.get(field, "")
                    writer.writerow(row)

        logger.info("Per-request CSV: %s", csv_path)

    @staticmethod
    def _build_disconnection_index(stage_summaries):
        """Build a set of request_ids that experienced disconnections."""
        disconnected = set()
        for summary in stage_summaries:
            for disc in summary.get("disconnections", []):
                rid = disc.get("request_id")
                if rid:
                    disconnected.add(rid)
        return disconnected

    # ------------------------------------------------------------------
    # results_resources.csv
    # ------------------------------------------------------------------

    # pylint: disable=too-many-locals
    @staticmethod
    def export_resources_csv(
            output_dir, stage_summaries,
            resource_rows, client_rows, args,
    ):
        """Write per-stage resource CSV with test configuration.

        One row per stage with server and client resource snapshots,
        wall clock time, thread deltas, and test config metadata.
        """
        if not output_dir:
            return

        csv_path = os.path.join(output_dir, "results_resources.csv")
        run_id = time.strftime("%Y-%m-%d_%H%M")
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

        fieldnames = [
            "run_id", "timestamp", "agent",
            "stage", "round", "concurrent", "wall_clock_sec",
            "server_before_rss", "server_settled_rss",
            "server_rss_delta",
            "server_before_threads", "server_peak_threads",
            "server_settled_threads", "server_thread_delta",
            "server_fds", "server_conns", "server_cpu",
            "server_children",
            "client_before_rss", "client_peak_rss",
            "client_settled_rss", "client_rss_delta",
            "client_cpu", "client_fds", "client_threads",
            "total_retries", "amplification",
            "rate_limit_retries", "api_error_retries",
            "key_error_retries", "value_error_retries",
            "other_retries",
            "primary_started", "primary_finished",
            "total_started", "total_finished",
            "disconnections",
            "new_threads", "reused_threads", "reuse_pct",
            "mode", "max_workers", "timeout",
            "idle_timeout", "settle_time",
        ]

        with open(csv_path, "w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for idx, summary in enumerate(stage_summaries):
                srv = (
                    resource_rows[idx]
                    if idx < len(resource_rows) else None
                )
                cli = (
                    client_rows[idx]
                    if idx < len(client_rows) else None
                )

                row = {
                    "run_id": run_id,
                    "timestamp": timestamp,
                    "agent": args.agent,
                    "stage": summary.get("stage", 0),
                    "round": summary.get("round", 1),
                    "concurrent": summary.get("concurrent", 0),
                    "wall_clock_sec": (
                        f"{summary.get('elapsed', 0):.2f}"
                    ),
                    "total_retries": (
                        summary.get("total_retries", 0)
                        if summary.get("has_server_log")
                        else ""
                    ),
                    "amplification": (
                        f"{summary.get('amplification', 1.0):.2f}"
                        if summary.get("has_server_log")
                        else ""
                    ),
                    "primary_started": (
                        summary.get("primary_started", 0)
                        if summary.get("has_server_log")
                        else ""
                    ),
                    "primary_finished": (
                        summary.get("primary_finished", 0)
                        if summary.get("has_server_log")
                        else ""
                    ),
                    "total_started": (
                        summary.get("total_started", 0)
                        if summary.get("has_server_log")
                        else ""
                    ),
                    "total_finished": (
                        summary.get("total_finished", 0)
                        if summary.get("has_server_log")
                        else ""
                    ),
                    "disconnections": (
                        len(summary.get("disconnections", []))
                        if summary.get("has_server_log")
                        else ""
                    ),
                }

                CsvExporter._fill_retry_breakdown(
                    row, summary,
                )
                CsvExporter._fill_pool_reuse(row, summary)

                row.update({
                    "mode": (
                        "ramp" if args.ramp else "flat"
                    ),
                    "max_workers": args.max_workers,
                    "timeout": args.timeout,
                    "idle_timeout": args.idle_timeout,
                    "settle_time": args.settle_time,
                })

                CsvExporter._fill_server_resource_row(row, srv, summary)
                CsvExporter._fill_client_resource_row(row, cli)
                writer.writerow(row)

        logger.info("Resources CSV: %s", csv_path)

    @staticmethod
    def _fill_server_resource_row(row, srv_tuple, summary):
        """Populate server resource columns from a resource tuple."""
        if srv_tuple is None:
            return
        row["server_before_rss"] = srv_tuple[1]
        row["server_settled_rss"] = srv_tuple[2]
        row["server_rss_delta"] = srv_tuple[3]
        row["server_fds"] = srv_tuple[4]
        before_threads = summary.get("before_threads", "")
        settled_threads = summary.get("after_threads", "")
        peak_threads = summary.get("peak_threads", "")
        row["server_before_threads"] = before_threads
        row["server_peak_threads"] = peak_threads
        row["server_settled_threads"] = settled_threads
        if before_threads != "" and settled_threads != "":
            row["server_thread_delta"] = (
                settled_threads - before_threads
            )
        row["server_conns"] = srv_tuple[7]
        row["server_cpu"] = srv_tuple[8]
        row["server_children"] = srv_tuple[9]

    @staticmethod
    def _fill_client_resource_row(row, cli_tuple):
        """Populate client resource columns from a client resource tuple."""
        if cli_tuple is None:
            return
        row["client_before_rss"] = cli_tuple[1]
        row["client_peak_rss"] = cli_tuple[2]
        row["client_settled_rss"] = cli_tuple[3]
        row["client_rss_delta"] = cli_tuple[4]
        row["client_cpu"] = cli_tuple[5]
        row["client_fds"] = cli_tuple[6]
        row["client_threads"] = cli_tuple[7]

    # ------------------------------------------------------------------
    # results_per_network.csv
    # ------------------------------------------------------------------

    @staticmethod
    def export_per_network_csv(output_dir, stage_summaries, agent_name):
        """Write per-network CSV with one row per sub-network per request.

        Only generated when server log data includes per-network
        token accounting. Each row contains the sub-network name,
        its token usage, LLM calls, duration, and cost.
        """
        if not output_dir:
            return

        rows = CsvExporter._collect_network_rows(
            stage_summaries, agent_name,
        )
        if not rows:
            return

        csv_path = os.path.join(output_dir, "results_per_network.csv")
        fieldnames = [
            "run_id", "timestamp", "agent",
            "stage", "round", "request_id",
            "network", "llm_calls", "total_tokens",
            "prompt_tokens", "completion_tokens",
            "duration_sec", "cost_usd", "model",
        ]

        with open(csv_path, "w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

        logger.info("Per-network CSV: %s", csv_path)

    @staticmethod
    def _collect_network_rows(stage_summaries, agent_name):
        """Build rows from per-network token data in stage summaries."""
        run_id = time.strftime("%Y-%m-%d_%H%M")
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        rows = []

        for summary in stage_summaries:
            stage = summary.get("stage", 0)
            round_num = summary.get("round", 1)
            for result in summary.get("results", []):
                networks = result.get("network_tokens", {})
                rid = result.get("request_id", "")
                for network_name, net_data in networks.items():
                    p_tok = net_data.get("prompt_tokens", 0)
                    c_tok = net_data.get("completion_tokens", 0)
                    model = net_data.get("model", "unknown")
                    rows.append({
                        "run_id": run_id,
                        "timestamp": timestamp,
                        "agent": agent_name,
                        "stage": stage,
                        "round": round_num,
                        "request_id": rid,
                        "network": network_name,
                        "llm_calls": net_data.get("llm_calls", 0),
                        "total_tokens": net_data.get(
                            "total_tokens", 0,
                        ),
                        "prompt_tokens": p_tok,
                        "completion_tokens": c_tok,
                        "duration_sec": (
                            f"{net_data.get('duration', 0):.2f}"
                        ),
                        "cost_usd": (
                            f"{estimate_cost(p_tok, c_tok, model):.6f}"
                        ),
                        "model": model,
                    })
        return rows

    # ------------------------------------------------------------------
    # Retry and pool reuse helpers
    # ------------------------------------------------------------------

    _KNOWN_RETRY_TYPES = {
        "RateLimitError": "rate_limit_retries",
        "APIError": "api_error_retries",
        "KeyError": "key_error_retries",
        "ValueError": "value_error_retries",
    }

    @staticmethod
    def _fill_retry_breakdown(row, summary):
        """Populate per-error-type retry columns from stage summary."""
        has_log = summary.get("has_server_log", False)
        retries = summary.get("retries", {})

        known_total = 0
        for error_type, col_name in CsvExporter._KNOWN_RETRY_TYPES.items():
            count = retries.get(error_type, 0)
            row[col_name] = count if has_log else ""
            known_total += count

        total = sum(retries.values()) if retries else 0
        row["other_retries"] = (
            (total - known_total) if has_log else ""
        )

    @staticmethod
    def _fill_pool_reuse(row, summary):
        """Populate pool reuse columns from thread data."""
        before_threads = summary.get("before_threads")
        after_threads = summary.get("after_threads")
        total_started = summary.get("total_started")

        if (
            before_threads is None
            or after_threads is None
            or total_started is None
            or total_started <= 0
        ):
            return

        new_threads = max(after_threads - before_threads, 0)
        reused = max(total_started - new_threads, 0)
        reuse_pct = reused / total_started * 100.0

        row["new_threads"] = new_threads
        row["reused_threads"] = reused
        row["reuse_pct"] = f"{reuse_pct:.1f}"

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _percentile(sorted_data, pct):
        """Calculate percentile from a sorted list."""
        if not sorted_data:
            return 0
        k = (len(sorted_data) - 1) * pct / 100.0
        f = int(k)
        c = f + 1
        if c >= len(sorted_data):
            return sorted_data[-1]
        return (
            sorted_data[f]
            + (k - f) * (sorted_data[c] - sorted_data[f])
        )
