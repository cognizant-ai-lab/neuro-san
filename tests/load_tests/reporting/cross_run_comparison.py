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

"""Cross-run comparison — scan output directories and compare metrics."""

import json
import logging
import os

from tests.load_tests.config import fmt_duration
from tests.load_tests.config import SEPARATOR_WIDTH
from tests.load_tests.reporting.table_formatter import TableFormatter

logger = logging.getLogger(__name__)


class CrossRunComparison:
    """Scans a base directory for raw_results.json files and logs
    a comparison table across runs."""

    def __init__(self, base_dir) -> None:
        self._base_dir = base_dir

    def run(self) -> None:
        """Scan for runs and log the comparison table."""
        runs = self._collect_runs()
        if not runs:
            logger.info(
                "No raw_results.json files found in %s",
                self._base_dir,
            )
            return
        runs.sort(key=lambda r: r.get("num_requests", 0))
        self._log_table(runs)

    def _collect_runs(self):
        """Walk subdirectories for raw_results.json and extract metrics."""
        runs = []
        for entry in os.listdir(self._base_dir):
            json_path = os.path.join(
                self._base_dir, entry, "raw_results.json",
            )
            if not os.path.isfile(json_path):
                continue
            metrics = self._extract_metrics(json_path, entry)
            if metrics is not None:
                runs.append(metrics)
        return runs

    @staticmethod
    def _extract_metrics(json_path, folder_name):
        """Parse a raw_results.json and return key metrics."""
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None

        config = data.get("config", {})
        aggregates = data.get("aggregates", {})
        num_requests = config.get(
            "num_requests",
            aggregates.get("total_requests", 0),
        )
        total_elapsed = aggregates.get(
            "total_elapsed_seconds", 0,
        )
        failed = aggregates.get("failed", 0)

        all_results = []
        for stage in data.get("stage_summaries", []):
            all_results.extend(stage.get("results", []))

        ttfr_values = [
            r.get("ttft", 0) for r in all_results
            if r.get("ttft", 0) > 0
        ]
        avg_ttfr = (
            sum(ttfr_values) / len(ttfr_values)
            if ttfr_values else 0
        )

        durations = [
            r.get("elapsed", 0) for r in all_results
        ]
        avg_duration = (
            sum(durations) / len(durations)
            if durations else 0
        )

        return {
            "folder": folder_name,
            "num_requests": num_requests,
            "wall_time": total_elapsed,
            "avg_per_req": avg_duration,
            "ttfr_avg": avg_ttfr,
            "failed": failed,
        }

    @staticmethod
    def _log_table(runs):
        """Log the comparison table with pct change from prior row."""
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  CROSS-RUN COMPARISON")
        logger.info("=" * SEPARATOR_WIDTH)

        header = [
            "Folder", "Requests", "Wall Time",
            "Avg/req", "TTFR avg", "Failed",
        ]
        rows = []
        metric_keys = [
            "num_requests", "wall_time",
            "avg_per_req", "ttfr_avg", "failed",
        ]
        prev = None
        for run in runs:
            deltas = CrossRunComparison._compute_deltas(
                prev, run, metric_keys,
            )
            rows.append((
                run.get("folder", ""),
                CrossRunComparison._val_with_delta(
                    str(run.get("num_requests", 0)),
                    deltas.get("num_requests"),
                ),
                CrossRunComparison._val_with_delta(
                    fmt_duration(run.get("wall_time", 0)),
                    deltas.get("wall_time"),
                ),
                CrossRunComparison._val_with_delta(
                    fmt_duration(run.get("avg_per_req", 0)),
                    deltas.get("avg_per_req"),
                ),
                CrossRunComparison._val_with_delta(
                    fmt_duration(run.get("ttfr_avg", 0)),
                    deltas.get("ttfr_avg"),
                ),
                CrossRunComparison._val_with_delta(
                    str(run.get("failed", 0)),
                    deltas.get("failed"),
                ),
            ))
            prev = run
        TableFormatter.log_table(header, rows)

    @staticmethod
    def _compute_deltas(prev, current, keys):
        """Compute percentage change from prev to current for each key."""
        if prev is None:
            return {}
        deltas = {}
        for key in keys:
            prev_val = prev.get(key, 0)
            curr_val = current.get(key, 0)
            if prev_val > 0:
                deltas[key] = (
                    (curr_val - prev_val) / prev_val * 100
                )
        return deltas

    @staticmethod
    def _val_with_delta(formatted_val, delta_pct):
        """Append percentage change suffix if available."""
        if delta_pct is None:
            return formatted_val
        sign = "+" if delta_pct >= 0 else ""
        return f"{formatted_val} ({sign}{delta_pct:.0f}%)"
