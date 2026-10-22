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

import json
import logging
import os
import time
from argparse import Namespace
from logging import Logger
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import psutil

from tests.load_tests.load_test_constants import HISTORY_FILE_NAME
from tests.load_tests.load_test_constants import HISTORY_THRESHOLDS_SECONDS
from tests.load_tests.load_test_constants import HISTORY_UNKNOWN_FILE_NAME
from tests.load_tests.load_test_constants import STATUS_CREATED
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor

logger: Logger = logging.getLogger(__name__)


class HistoryRecorder:
    """
    Appends one trend record per run to the history JSONL files, for plotting later.

    Successful runs go to history.jsonl so the trend file stays clean for plotting. Runs that could not
    determine the server version or completed no requests go to history_unknown.jsonl, so they are kept
    for debugging without polluting the trend data. Writing is best-effort: a write failure is logged and
    never fails the run.
    """

    PERCENT_PER_CORE: int = 100

    def __init__(self, args: Namespace, output_base: str) -> None:
        """
        Create a history recorder for one load-test run.

        :param args: Parsed load-test arguments; uses history_file, host and agent
        :param output_base: Base output directory, holding the history files when --history-file is not given
        """
        self._args: Namespace = args
        self._output_base: str = output_base

    def get_history_path(self, successful: bool = True) -> str:
        """
        Return the append-only trend-history JSONL path.

        Honours --history-file (the unknown records go to a sibling "*_unknown" file) and otherwise
        defaults to <output-base>/history[_unknown].jsonl, so records accumulate outside the per-run
        output directories.

        :param successful: True for the trend file of good runs, False for the unknown file
        :return: The history file path
        """
        if self._args.history_file:
            if successful:
                return self._args.history_file
            root, ext = os.path.splitext(self._args.history_file)
            unknown_ext: str = ext or ".jsonl"
            return f"{root}_unknown{unknown_ext}"
        name: str = HISTORY_UNKNOWN_FILE_NAME
        if successful:
            name = HISTORY_FILE_NAME
        history_path: str = os.path.join(self._output_base, name)
        return history_path

    def log_existing_history_files(self) -> None:
        """
        Log the path of each history file that exists.
        """
        history_paths: List[str] = [self.get_history_path(), self.get_history_path(successful=False)]
        history_path: str
        # Log each history file that exists.
        for history_path in history_paths:
            if os.path.isfile(history_path):
                logger.info("  History:     %s", history_path)

    def append_client_record(self, stage_summaries: List[Dict[str, Any]], neuro_san_version: Optional[str]) -> None:
        """
        Append one trend record for a client run.

        Records how many requests completed under each fixed time threshold, plus the neuro-san version,
        so throughput can be tracked over time. Does nothing when the run has no results.

        :param stage_summaries: Stage summaries of the run, from StageSummaryBuilder.build_stage_summary()
        :param neuro_san_version: Server neuro-san version, or None when unknown
        """
        stage_totals: Dict[str, Any] = HistoryRecorder._merge_stage_summaries(stage_summaries)
        results: List[Dict[str, Any]] = stage_totals.get("results")
        server_errors: List[Dict[str, str]] = stage_totals.get("server_errors")
        tool_warnings: List[Dict[str, str]] = stage_totals.get("tool_warnings")
        if not results:
            return

        timings: Dict[str, List[float]] = HistoryRecorder._successful_timings(results)
        durations_seconds: List[float] = timings.get("durations_seconds")
        first_response_seconds: List[float] = timings.get("first_response_seconds")
        completed: int = len(durations_seconds)
        avg_duration_seconds: float = HistoryRecorder._average(durations_seconds)
        avg_first_response_seconds: float = HistoryRecorder._average(first_response_seconds)
        record: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "neuro_san_version": neuro_san_version or "unknown",
            "host": self._args.host,
            "agent": self._args.agent,
            "transport": "http",
            "total_requests": len(results),
            "completed": completed,
            "avg_first_response_s": avg_first_response_seconds,
            "avg_duration_s": avg_duration_seconds,
            "wall_time_s": stage_totals.get("wall_time_seconds"),
            "server_error_count": len(server_errors),
            "tool_warning_count": len(tool_warnings),
            "server_errors": server_errors,
            "tool_warnings": tool_warnings,
        }
        HistoryRecorder._add_completed_within_counts(record, durations_seconds)
        successful: bool = completed > 0 and record.get("neuro_san_version") != "unknown"
        self._write_record(record, successful)

    # Each record field comes from one argument, so the server-only round passes them all.
    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    def append_server_record(self, neuro_san_version: Optional[str], expected: int, received: int,
                             elapsed_seconds: float, peak_server: Optional[Dict[str, Any]],
                             peak_system_cpu_percent: Optional[float],
                             primary_pairs: Optional[List[Dict[str, Any]]],
                             server_errors: Optional[List[Dict[str, str]]],
                             tool_warnings: Optional[List[Dict[str, str]]]) -> None:
        """
        Append one trend record for a server-only round.

        Records the server's resource peaks (CPU cores, RSS in GB), its neuro-san version, and the
        server-side processing durations from the primary agent's Start/Finish log pairs. Keyed with
        mode="server-only" so it is distinguishable from client records in the same file.

        :param neuro_san_version: Server neuro-san version, or None when unknown
        :param expected: Number of requests the round expects
        :param received: Number of requests the server received
        :param elapsed_seconds: Round wall time in seconds
        :param peak_server: Peak server snapshot with "rss" in megabytes, or None
        :param peak_system_cpu_percent: Peak system CPU percent over all cores, or None
        :param primary_pairs: Primary agent Start/Finish pairs with "duration_seconds", "start_ts" and
            "finish_ts", or None
        :param server_errors: Server errors found in the server log, or None
        :param tool_warnings: Tool warnings found in the server log, or None
        """
        pairs: List[Dict[str, Any]] = primary_pairs or []
        durations_seconds: List[float] = []
        pair: Dict[str, Any]
        # Collect the positive server-side duration of each primary request.
        for pair in pairs:
            pair_duration: Any = pair.get("duration_seconds")
            if not isinstance(pair_duration, (int, float)):
                continue
            pair_duration_seconds: float = pair_duration
            if pair_duration_seconds > 0:
                durations_seconds.append(float(pair_duration_seconds))
        avg_duration_seconds: float = HistoryRecorder._average(durations_seconds)
        cpu_percent: float = peak_system_cpu_percent or 0.0
        core_count: int = psutil.cpu_count() or 1
        peak_cpu_cores: float = round(cpu_percent / HistoryRecorder.PERCENT_PER_CORE * core_count, 2)
        peak_memory_gigabytes: Optional[float] = None
        if peak_server:
            peak_rss_megabytes: float = peak_server.get("rss", 0.0)
            peak_gigabytes: float = peak_rss_megabytes / ResourceMonitor.MEGABYTES_PER_GIGABYTE
            peak_memory_gigabytes = round(peak_gigabytes, 2)
        first_completed_seconds: float = HistoryRecorder._time_to_first_completed(pairs)
        errors: List[Dict[str, str]] = server_errors or []
        warnings: List[Dict[str, str]] = tool_warnings or []
        record: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "neuro_san_version": neuro_san_version or "unknown",
            "host": self._args.host,
            "agent": self._args.agent,
            "mode": "server-only",
            "expected_requests": expected,
            "received_requests": received,
            "peak_cpu_cores": peak_cpu_cores,
            "peak_memory_gb": peak_memory_gigabytes,
            "time_to_first_completed_s": first_completed_seconds,
            "avg_duration_s": avg_duration_seconds,
            "wall_time_s": round(elapsed_seconds, 2),
            "server_error_count": len(errors),
            "tool_warning_count": len(warnings),
            "server_errors": errors,
            "tool_warnings": warnings,
        }
        HistoryRecorder._add_completed_within_counts(record, durations_seconds)
        successful: bool = received > 0 and record.get("neuro_san_version") != "unknown"
        self._write_record(record, successful)

    def _write_record(self, record: Dict[str, Any], successful: bool) -> None:
        """
        Append one JSON record to the trend-history file.

        :param record: The trend record
        :param successful: True for the trend file of good runs, False for history_unknown.jsonl
        """
        path: str = self.get_history_path(successful=successful)
        try:
            history_dir: str = os.path.dirname(path) or "."
            os.makedirs(history_dir, exist_ok=True)
            record_line: str = json.dumps(record) + "\n"
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(record_line)
            logger.info("  Trend history appended: %s", path)
        except OSError as exc:
            logger.warning("  Could not write trend history to %s: %s", path, exc)

    @staticmethod
    def _merge_stage_summaries(stage_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Merge the results, server errors, tool warnings and elapsed time of every stage.

        :param stage_summaries: Stage summaries of the run
        :return: A dictionary with "results", "server_errors" and "tool_warnings" lists over all stages,
            and "wall_time_seconds", the sum of the stage "elapsed" times rounded to 2 decimals
        """
        results: List[Dict[str, Any]] = []
        server_errors: List[Dict[str, str]] = []
        tool_warnings: List[Dict[str, str]] = []
        stage_elapsed_seconds: List[float] = []
        summary: Dict[str, Any]
        # Collect the results, server errors, tool warnings and elapsed time of every stage.
        for summary in stage_summaries:
            stage_results: List[Dict[str, Any]] = summary.get("results", [])
            results.extend(stage_results)
            stage_server_errors: List[Dict[str, str]] = summary.get("server_errors", [])
            server_errors.extend(stage_server_errors)
            stage_tool_warnings: List[Dict[str, str]] = summary.get("tool_warnings", [])
            tool_warnings.extend(stage_tool_warnings)
            elapsed_seconds: float = summary.get("elapsed", 0.0)
            stage_elapsed_seconds.append(elapsed_seconds)
        # sum() of floats is compensated, so it can differ from a += total in the last digit.
        wall_time_seconds: float = round(sum(stage_elapsed_seconds), 2)
        stage_totals: Dict[str, Any] = {
            "results": results,
            "server_errors": server_errors,
            "tool_warnings": tool_warnings,
            "wall_time_seconds": wall_time_seconds,
        }
        return stage_totals

    @staticmethod
    def _successful_timings(results: List[Dict[str, Any]]) -> Dict[str, List[float]]:
        """
        Collect the duration and the time to first response of each successful request.

        :param results: Request results of the run
        :return: A dictionary with "durations_seconds", the "elapsed" time of each successful request, and
            "first_response_seconds", each positive "time_to_first_response" of a successful request
        """
        durations_seconds: List[float] = []
        first_response_seconds: List[float] = []
        result: Dict[str, Any]
        # Collect the duration and the time to first response of each successful request.
        for result in results:
            if result.get("status") != STATUS_CREATED:
                continue
            duration_seconds: float = result.get("elapsed", 0.0)
            durations_seconds.append(duration_seconds)
            time_to_first_response_seconds: float = result.get("time_to_first_response", 0.0)
            if time_to_first_response_seconds > 0:
                first_response_seconds.append(time_to_first_response_seconds)
        timings: Dict[str, List[float]] = {
            "durations_seconds": durations_seconds,
            "first_response_seconds": first_response_seconds,
        }
        return timings

    @staticmethod
    def _add_completed_within_counts(record: Dict[str, Any], durations_seconds: List[float]) -> None:
        """
        Add a "completed_within_<N>s" count to the record for each history threshold.

        :param record: The trend record, updated in place
        :param durations_seconds: Request durations in seconds
        """
        threshold_seconds: int
        # Count the requests that completed within each threshold.
        for threshold_seconds in HISTORY_THRESHOLDS_SECONDS:
            within_count: int = 0
            duration_seconds: float
            # Count the durations at or under this threshold.
            for duration_seconds in durations_seconds:
                if duration_seconds <= threshold_seconds:
                    within_count += 1
            record[f"completed_within_{int(threshold_seconds)}s"] = within_count

    @staticmethod
    def _average(values: List[float]) -> float:
        """
        Return the average of the values, rounded to 2 decimals.

        :param values: Values to average
        :return: The rounded average, or 0.0 when there are no values
        """
        if not values:
            return 0.0
        average: float = round(sum(values) / len(values), 2)
        return average

    @staticmethod
    def _time_to_first_completed(primary_pairs: List[Dict[str, Any]]) -> float:
        """
        Return the seconds from the first request's Start to the first request's Finish.

        This is the server-side time; it is not the client's per-request time to first response, which the
        server log has no way to measure.

        :param primary_pairs: Primary agent Start/Finish pairs with "start_ts" and "finish_ts"
        :return: The seconds, rounded to 2 decimals, or 0.0 when no primary request has a Start and a Finish
        """
        first_start_seconds: Optional[float] = None
        first_finish_seconds: Optional[float] = None
        pair: Dict[str, Any]
        # Keep the earliest Start and the earliest Finish time.
        for pair in primary_pairs:
            start_ts: Any = pair.get("start_ts")
            if isinstance(start_ts, (int, float)):
                start_seconds: float = start_ts
                if first_start_seconds is None:
                    first_start_seconds = start_seconds
                first_start_seconds = min(first_start_seconds, start_seconds)
            finish_ts: Any = pair.get("finish_ts")
            if isinstance(finish_ts, (int, float)):
                finish_seconds: float = finish_ts
                if first_finish_seconds is None:
                    first_finish_seconds = finish_seconds
                first_finish_seconds = min(first_finish_seconds, finish_seconds)
        if first_start_seconds is None or first_finish_seconds is None:
            return 0.0
        time_to_first_completed_seconds: float = round(first_finish_seconds - first_start_seconds, 2)
        return time_to_first_completed_seconds
