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

"""CSV export — per-request and summary data for analysis."""

import csv
import logging
import os
import time
from typing import Any
from typing import Dict
from typing import List

from tests.load_tests.config import STATUS_CREATED

logger = logging.getLogger(__name__)


class CsvExporter:
    """Writes per-request and summary CSV files for analysis."""

    # pylint: disable=too-many-locals
    @staticmethod
    def export_per_request_csv(output_dir, stage_summaries, agent_name):
        """Write per-request CSV with one row per request.

        Includes all data needed for LLM-based analysis.
        """
        if not output_dir:
            return

        csv_path = os.path.join(output_dir, "results_per_request.csv")
        run_id = time.strftime("%Y-%m-%d_%H%M")

        fieldnames = [
            "run_id", "timestamp", "agent", "stage", "round",
            "request_id", "status", "duration_sec", "prompt",
            "error",
        ]

        parsed_field_names = set()
        for summary in stage_summaries:
            for result in summary.get("results", []):
                for key in result:
                    if key not in {
                        "status", "elapsed", "prompt",
                        "error", "request_id",
                    }:
                        parsed_field_names.add(key)
        sorted_fields = sorted(parsed_field_names)
        fieldnames.extend(sorted_fields)

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(csv_path, "w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            request_num = 0
            for summary in stage_summaries:
                stage = summary.get("stage", 0)
                round_num = summary.get("round", 1)
                for result in summary.get("results", []):
                    request_num += 1
                    row = {
                        "run_id": run_id,
                        "timestamp": timestamp,
                        "agent": agent_name,
                        "stage": stage,
                        "round": round_num,
                        "request_id": result.get(
                            "request_id", f"request-{request_num}",
                        ),
                        "status": result.get("status", ""),
                        "duration_sec": (
                            f"{result.get('elapsed', 0):.2f}"
                        ),
                        "prompt": result.get("prompt", ""),
                        "error": result.get("error", ""),
                    }
                    for field in sorted_fields:
                        row[field] = result.get(field, "")
                    writer.writerow(row)

        logger.info("Per-request CSV: %s", csv_path)

    # pylint: disable=too-many-locals
    @staticmethod
    def export_summary_csv(output_dir, stage_summaries, agent_name):
        """Write summary CSV with one row per run for cross-run comparison."""
        if not output_dir:
            return

        csv_path = os.path.join(output_dir, "results_summary.csv")
        run_id = time.strftime("%Y-%m-%d_%H%M")

        all_results: List[Dict[str, Any]] = []
        total_requests = 0
        total_created = 0
        total_failed = 0
        total_time = 0.0

        for summary in stage_summaries:
            counts = summary.get("counts", {})
            total_requests += summary.get("concurrent", 0)
            total_created += counts.get(STATUS_CREATED, 0)
            total_failed += (
                counts.get("FAILED", 0)
                + counts.get("TIMEOUT", 0)
                + counts.get("KILLED", 0)
            )
            total_time += summary.get("elapsed", 0)
            all_results.extend(summary.get("results", []))

        durations = [r.get("elapsed", 0) for r in all_results]
        durations.sort()

        avg_duration = (
            sum(durations) / len(durations) if durations else 0
        )
        p50_duration = CsvExporter._percentile(durations, 50)
        p90_duration = CsvExporter._percentile(durations, 90)

        token_totals = [
            r.get("total_tokens", 0)
            for r in all_results if r.get("total_tokens")
        ]
        token_totals.sort()
        has_tokens = len(token_totals) > 0

        fieldnames = [
            "run_id", "date", "agent", "total_requests",
            "completed", "failed",
            "avg_duration_sec", "p50_duration_sec", "p90_duration_sec",
            "total_time_sec",
        ]
        if has_tokens:
            fieldnames.extend([
                "total_tokens", "avg_tokens",
                "p50_tokens", "p90_tokens",
                "max_tokens", "total_prompt_tokens",
                "total_completion_tokens",
                "total_llm_calls", "model",
            ])

        row = {
            "run_id": run_id,
            "date": time.strftime("%Y-%m-%d"),
            "agent": agent_name,
            "total_requests": total_requests,
            "completed": total_created,
            "failed": total_failed,
            "avg_duration_sec": f"{avg_duration:.2f}",
            "p50_duration_sec": f"{p50_duration:.2f}",
            "p90_duration_sec": f"{p90_duration:.2f}",
            "total_time_sec": f"{total_time:.2f}",
        }

        if has_tokens:
            avg_tokens = sum(token_totals) / len(token_totals)
            total_prompt = sum(
                r.get("prompt_tokens", 0) for r in all_results
            )
            total_comp = sum(
                r.get("completion_tokens", 0) for r in all_results
            )
            total_llm = sum(
                r.get("llm_calls", 0) for r in all_results
            )
            models = set(
                r.get("model") for r in all_results if r.get("model")
            )
            row.update({
                "total_tokens": sum(token_totals),
                "avg_tokens": int(avg_tokens),
                "p50_tokens": int(
                    CsvExporter._percentile(token_totals, 50),
                ),
                "p90_tokens": int(
                    CsvExporter._percentile(token_totals, 90),
                ),
                "max_tokens": max(token_totals),
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_comp,
                "total_llm_calls": total_llm,
                "model": ";".join(sorted(models)),
            })

        with open(csv_path, "w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(row)

        logger.info("Summary CSV: %s", csv_path)

    @staticmethod
    def append_resource_history(
            stage_summaries, resource_rows, client_rows,
    ):
        """Append resource data to a persistent CSV history file.

        Only writes data from successful runs (all requests created).
        """
        all_created = all(
            s.get("counts", {}).get(STATUS_CREATED, 0)
            == s.get("concurrent")
            for s in stage_summaries
        )
        if not all_created:
            return

        history_path = "/tmp/load_test/adv/resource_history.csv"
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        write_header = not os.path.exists(history_path)

        now = time.strftime("%Y-%m-%d %H:%M:%S")
        server_fields = [
            "datetime", "concurrent", "before_rss", "settled_rss",
            "rss_delta", "fds", "threads", "conns", "cpu",
            "children", "side",
        ]

        with open(
                history_path, "a", encoding="utf-8", newline="",
        ) as csvfile:
            writer = csv.writer(csvfile)
            if write_header:
                writer.writerow(server_fields)

            for row in resource_rows:
                writer.writerow([
                    now, row[0], row[1], row[2], row[3],
                    row[4], row[5], row[7], row[8], row[9],
                    "server",
                ])

            for row in client_rows:
                writer.writerow([
                    now, row[0], row[1], row[3], row[4],
                    row[6], row[7], "0", row[5], "0",
                    "client",
                ])

        logger.info("\nResource history appended: %s", history_path)

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
