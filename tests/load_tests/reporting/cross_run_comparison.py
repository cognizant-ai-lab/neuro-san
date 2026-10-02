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

"""Cross-run comparison — scan output directories and compare metrics."""

import json
import logging
import os
import re
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from tests.load_tests.config import SEPARATOR_WIDTH
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.cost_estimator import CostEstimator
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.table_formatter import TableFormatter

_NORMAL_LLM_CALLS = 4
_LOOP_THRESHOLD = 10
_SERVER_TOKEN_RE = re.compile(
    r"(request-\d+):\s*([\d,]+)\s*tokens"
    r"\s*\(([\d,]+)\s*prompt\s*\+\s*([\d,]+)\s*completion\),"
    r"\s*(\d+)\s*LLM call\(s\),"
    r"\s*model=([^\s]+)",
)

logger = logging.getLogger(__name__)


class CrossRunComparison:
    """Scans a base directory for raw_results.json files and logs
    a comparison table across runs."""

    def __init__(self, base_dir: str, agent_filter: Optional[List[str]] = None, baseline_requests: int = 0,
                 run_filter: Optional[List[str]] = None) -> None:
        """
        Constructor.

        :param base_dir: Directory whose subdirectories each hold one run's raw_results.json
        :param agent_filter: Agent names to include; None or empty includes every agent
        :param baseline_requests: Leave out runs with fewer requests than this; 0 keeps every run
        :param run_filter: Run folder names to include, with no deduplication; None or empty includes every folder
        """
        self._base_dir = base_dir
        self._agent_filter: set = (
            set(agent_filter) if agent_filter else set()
        )
        self._baseline_requests = baseline_requests
        self._run_filter: set = (
            set(run_filter) if run_filter else set()
        )

    def run(self) -> None:
        """Scan for runs and log comparison tables by agent."""
        all_runs: List[Dict[str, Any]] = self._collect_runs()
        if not all_runs:
            logger.info(
                "No raw_results.json files found in %s",
                self._base_dir,
            )
            return
        groups: Dict[str, List[Dict[str, Any]]] = self._group_by_agent(all_runs)
        for agent_name in sorted(groups):
            runs: List[Dict[str, Any]] = (
                groups[agent_name]
                if self._run_filter
                else self._deduplicate(groups[agent_name])
            )
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
            self._log_validation_loops(runs)

    def _collect_runs(self) -> List[Dict[str, Any]]:
        """
        Walk subdirectories for raw_results.json and extract metrics.

        :return: Metrics for each run folder that has a readable raw_results.json
        """
        runs: List[Dict[str, Any]] = []
        for entry in os.listdir(self._base_dir):
            if (self._run_filter
                    and entry not in self._run_filter):
                continue
            json_path: str = os.path.join(
                self._base_dir, entry, "raw_results.json",
            )
            if not os.path.isfile(json_path):
                continue
            metrics: Optional[Dict[str, Any]] = self._extract_metrics(json_path, entry)
            if metrics is not None:
                runs.append(metrics)
        return runs

    @staticmethod
    def _deduplicate(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Keep only the latest run per request count.

        :param runs: Metrics for one agent's runs
        :return: One run per num_requests, the one whose folder name sorts last
        """
        by_count: Dict[int, Dict[str, Any]] = {}
        for run in runs:
            count: int = run.get("num_requests", 0)
            existing: Optional[Dict[str, Any]] = by_count.get(count)
            if (existing is None
                    or run.get("folder", "")
                    > existing.get("folder", "")):
                by_count[count] = run
        return list(by_count.values())

    @staticmethod
    def _extract_metrics(json_path: str, folder_name: str) -> Optional[Dict[str, Any]]:
        """
        Parse a raw_results.json and return key metrics.

        :param json_path: Path to the run's raw_results.json
        :param folder_name: Name of the run folder, stored as the run's folder
        :return: The run's metrics, or None when the file cannot be read or parsed
        """
        data: Dict[str, Any]
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None

        aggregates: Dict[str, Any] = data.get("aggregates", {})
        stages: List[Dict[str, Any]] = data.get("stage_summaries", [])
        all_results: List[Dict[str, Any]] = []
        for stage in stages:
            all_results.extend(stage.get("results", []))
        created_results: List[Dict[str, Any]] = []
        result: Dict[str, Any]
        for result in all_results:
            if result.get("status") == STATUS_CREATED:
                created_results.append(result)

        agent: str = data.get("config", {}).get(
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
            "avg_success": CrossRunComparison._avg(created_results, "elapsed"),
            "time_to_first_response_avg": CrossRunComparison._avg(
                created_results, "time_to_first_response",
            ),
            "peak_rss": max(
                (s.get("peak_server_rss", 0) or 0
                 for s in stages),
                default=0,
            ),
            "succeeded": aggregates.get("passed", 0),
            "failed": aggregates.get("failed", 0),
            "fail_breakdown": CrossRunComparison._classify_failures(
                all_results,
            ),
        }

    @staticmethod
    def _classify_failures(all_results: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Categorize failed requests by failure reason.

        :param all_results: Every request result in the run
        :return: Failure category to count; "other" is added only when a reason matches no category
        """
        counts: Dict[str, int] = {
            "empty_llm": 0,
            "validation": 0,
            "incomplete": 0,
            "no_token_data": 0,
        }
        for result in all_results:
            if result.get("status") == STATUS_CREATED:
                continue
            reason: str = result.get("failure_reason", "") or ""
            if "empty LLM response" in reason:
                counts["empty_llm"] += 1
            elif "validation fix cycle" in reason:
                counts["validation"] += 1
            elif "incomplete response" in reason:
                counts["incomplete"] += 1
            elif "no token data" in reason:
                counts["no_token_data"] += 1
            else:
                counts.setdefault("other", 0)
                counts["other"] += 1
        return counts

    @staticmethod
    def _avg(results: List[Dict[str, Any]], key: str) -> float:
        """
        Compute average of a result field, ignoring zeros.

        :param results: Request results to average over
        :param key: Result field to average
        :return: Average of the values above 0, or 0 when there are none
        """
        values: List[float] = [
            r.get(key, 0) for r in results
            if r.get(key, 0) > 0
        ]
        if not values:
            return 0
        return sum(values) / len(values)

    def _group_by_agent(self, runs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group runs by agent name, applying filter if set.

        :param runs: Metrics for every run
        :return: Agent name to its runs, limited to agent_filter when set
        """
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for run in runs:
            agent: str = run.get("agent", "unknown")
            if (self._agent_filter
                    and agent not in self._agent_filter):
                continue
            groups.setdefault(agent, []).append(run)
        return groups

    @staticmethod
    def _log_table(runs: List[Dict[str, Any]], agent_name: str) -> None:
        """
        Log the comparison table with pct change from baseline.

        :param runs: One agent's runs sorted by num_requests; the first is the baseline
        :param agent_name: Agent name shown in the table title
        """
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  CROSS-RUN COMPARISON: %s", agent_name)
        logger.info("=" * SEPARATOR_WIDTH)

        header: List[str] = [
            "Folder", "Requests", "Succeeded",
            "Wall Time",
            "Avg success (duration)",
            "First resp avg", "Peak RSS",
            "Failed requests",
        ]
        rows: List[Tuple[str, ...]] = []
        metric_keys: List[str] = [
            "num_requests", "wall_time",
            "avg_success",
            "time_to_first_response_avg", "peak_rss",
            "failed",
        ]
        baseline: Optional[Dict[str, Any]] = runs[0] if runs else None
        for run in runs:
            ref: Optional[Dict[str, Any]] = baseline if run is not baseline else None
            deltas: Dict[str, float] = CrossRunComparison._compute_deltas(
                ref, run, metric_keys,
            )
            rows.append((
                run.get("folder", ""),
                CrossRunComparison._val_with_delta(
                    str(run.get("num_requests", 0)),
                    deltas.get("num_requests"),
                ),
                str(run.get("succeeded", 0)),
                CrossRunComparison._val_with_delta(
                    Formatters.fmt_duration(run.get("wall_time", 0)),
                    deltas.get("wall_time"),
                ),
                CrossRunComparison._fmt_optional(
                    run.get("avg_success", 0),
                    deltas.get("avg_success"),
                ),
                CrossRunComparison._fmt_time_to_first_response(
                    run.get("time_to_first_response_avg", 0),
                    deltas.get("time_to_first_response_avg"),
                ),
                CrossRunComparison._fmt_rss(
                    run.get("peak_rss", 0),
                    deltas.get("peak_rss"),
                ),
                CrossRunComparison._fmt_failed(
                    run.get("failed", 0),
                    run.get("num_requests", 0),
                    run.get("fail_breakdown", {}),
                ),
            ))
        TableFormatter.log_table(header, rows)

    def _log_validation_loops(self, runs: List[Dict[str, Any]]) -> None:
        """
        Log validation loop summary for runs that have them.

        :param runs: Runs whose server_tokens.log is checked
        """
        for run in runs:
            folder: str = run.get("folder", "")
            log_path: str = os.path.join(
                self._base_dir, folder, "server_tokens.log",
            )
            loops: List[Dict[str, Any]] = self._parse_validation_loops(log_path)
            if not loops:
                continue
            self._print_loop_summary(folder, loops)

    @staticmethod
    def _parse_validation_loops(log_path: str) -> List[Dict[str, Any]]:
        """
        Parse server_tokens.log for validation loop requests.

        :param log_path: Path to a run's server_tokens.log
        :return: One entry per request with at least _LOOP_THRESHOLD LLM calls; empty when the file is missing
        """
        if not os.path.isfile(log_path):
            return []
        loops: List[Dict[str, Any]] = []
        with open(log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                match: Optional[re.Match] = _SERVER_TOKEN_RE.search(line)
                if not match:
                    continue
                llm_calls: int = int(match.group(5))
                if llm_calls < _LOOP_THRESHOLD:
                    continue
                prompt: int = int(
                    match.group(3).replace(",", ""),
                )
                completion: int = int(
                    match.group(4).replace(",", ""),
                )
                model: str = match.group(6)
                retries: int = llm_calls - _NORMAL_LLM_CALLS
                cost: float = CostEstimator.estimate(
                    prompt, completion, model,
                )
                loops.append({
                    "request_id": match.group(1),
                    "llm_calls": llm_calls,
                    "retries": retries,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": prompt + completion,
                    "model": model,
                    "cost_usd": cost,
                })
        return loops

    @staticmethod
    def _print_loop_summary(folder: str, loops: List[Dict[str, Any]]) -> None:
        """
        Print aggregated validation loop stats.

        :param folder: Run folder name shown in the summary
        :param loops: Validation loop entries from _parse_validation_loops
        """
        total_retries: int = sum(
            lp.get("retries", 0) for lp in loops
        )
        total_tokens: int = sum(
            lp.get("total_tokens", 0) for lp in loops
        )
        total_cost: float = sum(
            lp.get("cost_usd", 0.0) for lp in loops
        )
        logger.info("")
        logger.info(
            "  Validation loops in %s "
            "(%s request(s)):",
            folder, len(loops),
        )
        logger.info(
            "    Total: %s retries, %s tokens, "
            "$%.2f",
            total_retries,
            f"{total_tokens:,}",
            total_cost,
        )
        for lp in sorted(
            loops, key=lambda x: x.get("retries", 0),
            reverse=True,
        ):
            logger.info(
                "    %s: %s retries, %s tokens "
                "($%.2f)",
                lp.get("request_id", ""),
                lp.get("retries", 0),
                f"{lp.get('total_tokens', 0):,}",
                lp.get("cost_usd", 0.0),
            )

    @staticmethod
    def _compute_deltas(prev: Optional[Dict[str, Any]], current: Dict[str, Any], keys: List[str]) -> Dict[str, float]:
        """
        Compute percentage change from prev to current for each key.

        :param prev: Baseline run metrics, or None for the baseline itself
        :param current: Metrics of the run being compared
        :param keys: Metric names to compare
        :return: Metric name to percent change; keys with a baseline of 0 are left out
        """
        if prev is None:
            return {}
        deltas: Dict[str, float] = {}
        for key in keys:
            prev_val: float = prev.get(key, 0)
            curr_val: float = current.get(key, 0)
            if prev_val > 0:
                deltas[key] = (
                    (curr_val - prev_val) / prev_val * 100
                )
        return deltas

    @staticmethod
    def _val_with_delta(formatted_val: str, delta_pct: Optional[float]) -> str:
        """
        Append percentage change suffix if available.

        :param formatted_val: Value already formatted for display
        :param delta_pct: Percent change against the baseline run, or None
        :return: e.g. '120 (+20%)', or formatted_val unchanged when delta_pct is None
        """
        if delta_pct is None:
            return formatted_val
        sign: str = "+" if delta_pct >= 0 else ""
        return f"{formatted_val} ({sign}{delta_pct:.0f}%)"

    @staticmethod
    def _fmt_optional(value: float, delta_pct: Optional[float]) -> str:
        """
        Format a duration, showing a dash when data is missing.

        :param value: Duration in seconds; 0 when unknown
        :param delta_pct: Percent change against the baseline run, or None
        :return: The formatted duration, or a dash when value is 0
        """
        if value <= 0:
            return "\u2014"
        return CrossRunComparison._val_with_delta(
            Formatters.fmt_duration(value), delta_pct,
        )

    @staticmethod
    def _fmt_time_to_first_response(value: float, delta_pct: Optional[float]) -> str:
        """
        Format time to first response, showing a dash when data is missing.

        :param value: Average time to first response in seconds; 0 when unknown
        :param delta_pct: Percent change against the baseline run, or None
        :return: The formatted value, or a dash when value is 0
        """
        if value <= 0:
            return "\u2014"
        return CrossRunComparison._val_with_delta(
            Formatters.fmt_duration(value), delta_pct,
        )

    @staticmethod
    def _fmt_rss(value: float, delta_pct: Optional[float]) -> str:
        """
        Format peak RSS, showing a dash when data is missing.

        :param value: Peak RSS in megabytes; 0 when unknown
        :param delta_pct: Percent change against the baseline run, or None
        :return: The formatted RSS, or a dash when value is 0
        """
        if value <= 0:
            return "\u2014"
        return CrossRunComparison._val_with_delta(
            Formatters.format_rss(value), delta_pct,
        )

    @staticmethod
    def _fmt_failed(count: int, total: int, breakdown: Dict[str, int]) -> str:
        """
        Format failed count with optional breakdown.

        :param count: Number of failed requests
        :param total: Number of requests in the run, used for the percentage
        :param breakdown: Failure category to count, from _classify_failures
        :return: e.g. '3 (5%): 2 empty LLM, 1 other', or '0' when nothing failed
        """
        if count == 0:
            return "0"
        pct: int = (count * 100 // total) if total else 0
        base: str = f"{count} ({pct}%)"
        if not breakdown:
            return base
        labels: Tuple[Tuple[str, str], ...] = (
            ("empty_llm", "empty LLM"),
            ("validation", "validation"),
            ("incomplete", "incomplete"),
            ("no_token_data", "no token data"),
            ("other", "other"),
        )
        parts: List[str] = []
        for key, label in labels:
            val: int = breakdown.get(key, 0)
            if val:
                parts.append(f"{val} {label}")
        if not parts:
            return base
        return f"{base}: {', '.join(parts)}"
