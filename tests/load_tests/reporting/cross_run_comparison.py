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
from tests.load_tests.config import format_rss
from tests.load_tests.config import SEPARATOR_WIDTH
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.reporting.table_formatter import TableFormatter

logger = logging.getLogger(__name__)


class CrossRunComparison:
    """Scans a base directory for raw_results.json files and logs
    a comparison table across runs."""

    def __init__(
        self, base_dir, *,
        agent_filter=None,
        baseline_requests=0,
    ) -> None:
        self._base_dir = base_dir
        self._agent_filter: set = (
            set(agent_filter) if agent_filter else set()
        )
        self._baseline_requests = baseline_requests

    def run(self) -> None:
        """Scan for runs and log comparison tables by agent."""
        all_runs = self._collect_runs()
        if not all_runs:
            logger.info(
                "No raw_results.json files found in %s",
                self._base_dir,
            )
            return
        groups = self._group_by_agent(all_runs)
        for agent_name in sorted(groups):
            runs = self._deduplicate(groups[agent_name])
            if self._baseline_requests > 0:
                runs = [
                    r for r in runs
                    if r.get("num_requests", 0)
                    >= self._baseline_requests
                ]
            runs.sort(
                key=lambda r: r.get("num_requests", 0),
            )
            if not runs:
                continue
            self._log_table(runs, agent_name)

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
    def _deduplicate(runs):
        """Keep only the latest run per request count."""
        by_count = {}
        for run in runs:
            count = run.get("num_requests", 0)
            existing = by_count.get(count)
            if (existing is None
                    or run.get("folder", "")
                    > existing.get("folder", "")):
                by_count[count] = run
        return list(by_count.values())

    @staticmethod
    def _extract_metrics(json_path, folder_name):
        """Parse a raw_results.json and return key metrics."""
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None

        aggregates = data.get("aggregates", {})
        stages = data.get("stage_summaries", [])
        all_results = []
        for stage in stages:
            all_results.extend(stage.get("results", []))

        agent = data.get("config", {}).get(
            "agent", "unknown",
        )

        return {
            "agent": agent,
            "folder": folder_name,
            "num_requests": data.get("config", {}).get(
                "num_requests",
                aggregates.get("total_requests", 0),
            ),
            "wall_time": aggregates.get(
                "total_elapsed_seconds", 0,
            ),
            "avg_success": CrossRunComparison._avg(
                [
                    r for r in all_results
                    if r.get("status") == STATUS_CREATED
                ],
                "elapsed",
            ),
            "ttfr_avg": CrossRunComparison._avg(
                [
                    r for r in all_results
                    if r.get("status") == STATUS_CREATED
                ],
                "ttft",
            ),
            "peak_rss": max(
                (s.get("peak_server_rss", 0) or 0
                 for s in stages),
                default=0,
            ),
            "failed": aggregates.get("failed", 0),
            "fail_breakdown": CrossRunComparison._classify_failures(
                all_results,
            ),
        }

    @staticmethod
    def _classify_failures(all_results):
        """Categorize failed requests by failure reason."""
        empty_llm = 0
        validation = 0
        other = 0
        for result in all_results:
            if result.get("status") == STATUS_CREATED:
                continue
            reason = result.get("failure_reason", "") or ""
            if "empty LLM response" in reason:
                empty_llm += 1
            elif "validation fix cycle" in reason:
                validation += 1
            else:
                other += 1
        return {
            "empty_llm": empty_llm,
            "validation": validation,
            "other": other,
        }

    @staticmethod
    def _avg(results, key):
        """Compute average of a result field, ignoring zeros."""
        values = [
            r.get(key, 0) for r in results
            if r.get(key, 0) > 0
        ]
        if not values:
            return 0
        return sum(values) / len(values)

    def _group_by_agent(self, runs):
        """Group runs by agent name, applying filter if set."""
        groups = {}
        for run in runs:
            agent = run.get("agent", "unknown")
            if (self._agent_filter
                    and agent not in self._agent_filter):
                continue
            groups.setdefault(agent, []).append(run)
        return groups

    @staticmethod
    def _log_table(runs, agent_name):
        """Log the comparison table with pct change from baseline."""
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  CROSS-RUN COMPARISON: %s", agent_name)
        logger.info("=" * SEPARATOR_WIDTH)

        header = [
            "Folder", "Requests", "Wall Time",
            "Avg success (duration)",
            "TTFR avg", "Peak RSS",
            "Failed requests",
        ]
        rows = []
        metric_keys = [
            "num_requests", "wall_time",
            "avg_success",
            "ttfr_avg", "peak_rss",
            "failed",
        ]
        baseline = runs[0] if runs else None
        for run in runs:
            ref = baseline if run is not baseline else None
            deltas = CrossRunComparison._compute_deltas(
                ref, run, metric_keys,
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
                CrossRunComparison._fmt_optional(
                    run.get("avg_success", 0),
                    deltas.get("avg_success"),
                ),
                CrossRunComparison._fmt_ttfr(
                    run.get("ttfr_avg", 0),
                    deltas.get("ttfr_avg"),
                ),
                CrossRunComparison._fmt_rss(
                    run.get("peak_rss", 0),
                    deltas.get("peak_rss"),
                ),
                CrossRunComparison._fmt_failed(
                    run.get("failed", 0),
                    deltas.get("failed"),
                    run.get("fail_breakdown", {}),
                ),
            ))
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

    @staticmethod
    def _fmt_optional(value, delta_pct):
        """Format a duration, showing a dash when data is missing."""
        if value <= 0:
            return "\u2014"
        return CrossRunComparison._val_with_delta(
            fmt_duration(value), delta_pct,
        )

    @staticmethod
    def _fmt_ttfr(value, delta_pct):
        """Format TTFR, showing a dash when data is missing."""
        if value <= 0:
            return "\u2014"
        return CrossRunComparison._val_with_delta(
            fmt_duration(value), delta_pct,
        )

    @staticmethod
    def _fmt_rss(value, delta_pct):
        """Format peak RSS, showing a dash when data is missing."""
        if value <= 0:
            return "\u2014"
        return CrossRunComparison._val_with_delta(
            format_rss(value), delta_pct,
        )

    @staticmethod
    def _fmt_failed(count, delta_pct, breakdown):
        """Format failed count with optional breakdown."""
        base = CrossRunComparison._val_with_delta(
            str(count), delta_pct,
        )
        if count == 0 or not breakdown:
            return base
        parts = []
        empty_llm = breakdown.get("empty_llm", 0)
        validation = breakdown.get("validation", 0)
        other = breakdown.get("other", 0)
        if empty_llm:
            parts.append(f"{empty_llm} empty LLM")
        if validation:
            parts.append(f"{validation} validation")
        if other:
            parts.append(f"{other} other")
        if not parts:
            return base
        return f"{base} ({', '.join(parts)})"
