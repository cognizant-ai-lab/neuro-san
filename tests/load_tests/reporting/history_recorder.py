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

from json import dumps
from os import makedirs
from os.path import dirname
from os.path import isfile
from os.path import join
from os.path import splitext
from time import strftime
from argparse import Namespace
from logging import Logger
from logging import getLogger
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from psutil import cpu_count

from leaf_common.logging.sensitive_logger import SensitiveLogger

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor


class HistoryRecorder:
    """
    Appends one trend record per run to the history JSONL files, for plotting later.

    Successful runs go to history.jsonl so the trend file stays clean for plotting. Runs that could not
    determine the server version or completed no requests go to history_unknown.jsonl, so they are kept
    for debugging without polluting the trend data. Writing is best-effort: a write failure is logged and
    never fails the run.
    """

    def __init__(self, args: Namespace, output_base: str) -> None:
        """
        Create a history recorder for one load-test run.

        :param args: Parsed load-test arguments; uses history_file, host and agent
        :param output_base: Base output directory, holding the history files when --history-file is not given
        """
        self._args: Namespace = args
        self._output_base: str = output_base
        self.logger: Logger = getLogger(self.__class__.__name__)

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
            root, ext = splitext(self._args.history_file)
            unknown_ext: str = ext or ".jsonl"
            return f"{root}_unknown{unknown_ext}"
        name: str = LoadTestConstants.HISTORY_UNKNOWN_FILE_NAME
        if successful:
            name = LoadTestConstants.HISTORY_FILE_NAME
        history_path: str = join(self._output_base, name)
        return history_path

    def log_existing_history_files(self) -> None:
        """
        Log the path of each history file that exists.
        """
        history_paths: List[str] = [self.get_history_path(), self.get_history_path(successful=False)]
        history_path: str
        # Log each history file that exists.
        for history_path in history_paths:
            if isfile(history_path):
                self.logger.info("  History:     %s", history_path)

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
            "timestamp": strftime("%Y-%m-%dT%H:%M:%S%z"),
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

    def append_server_record(self, round_record: Dict[str, Any]) -> None:
        """
        Append one trend record for a server-only round.

        Records the server's resource peaks (CPU cores, RSS in GB), its neuro-san version, and the
        server-side processing durations from the primary agent's Start/Finish log pairs. Keyed with
        mode="server-only" so it is distinguishable from client records in the same file.

        :param round_record: The server-only round, as ServerOnlyMonitor builds it. Keys read here:
            "neuro_san_version": server neuro-san version, or None when unknown
            "expected": number of requests the round expects
            "count": number of requests the server received
            "elapsed_seconds": round wall time in seconds
            "peak_server": peak server snapshot with "rss_megabytes", or None
            "peak_system_cpu_percent": peak system CPU percent over all cores, or None
            "primary_pairs": primary agent Start/Finish pairs with "duration_seconds", "start_ts" and
                "finish_ts", or None
            "server_errors": server errors found in the server log, or None
            "tool_warnings": tool warnings found in the server log, or None
        """
        pairs: List[Dict[str, Any]] = round_record.get("primary_pairs") or []
        durations_seconds: List[float] = HistoryRecorder._positive_durations(pairs)
        record: Dict[str, Any] = self._server_round_record(round_record, pairs, durations_seconds)
        HistoryRecorder._add_server_log_findings(record, round_record)
        HistoryRecorder._add_completed_within_counts(record, durations_seconds)
        received: int = record.get("received_requests")
        successful: bool = received > 0 and record.get("neuro_san_version") != "unknown"
        self._write_record(record, successful)

    def _server_round_record(self, round_record: Dict[str, Any], pairs: List[Dict[str, Any]],
                             durations_seconds: List[float]) -> Dict[str, Any]:
        """
        Build the trend record of a server-only round, from its timestamp up to its wall time.

        :param round_record: The server-only round; append_server_record() lists the keys read here
        :param pairs: The round's primary agent Start/Finish pairs
        :param durations_seconds: The positive server-side duration of each primary request, in seconds
        :return: The record with the version, host, agent, request counts, resource peaks and timings
        """
        avg_duration_seconds: float = HistoryRecorder._average(durations_seconds)
        peak_cpu_cores: float = HistoryRecorder._peak_cpu_cores(round_record)
        peak_memory_gigabytes: Optional[float] = HistoryRecorder._peak_memory_gigabytes(round_record)
        first_completed_seconds: float = HistoryRecorder._time_to_first_completed(pairs)
        neuro_san_version: str = round_record.get("neuro_san_version") or "unknown"
        expected: int = round_record.get("expected")
        received: int = round_record.get("count")
        elapsed_seconds: float = round_record.get("elapsed_seconds")
        wall_time_seconds: float = round(elapsed_seconds, 2)
        record: Dict[str, Any] = {
            "timestamp": strftime("%Y-%m-%dT%H:%M:%S%z"),
            "neuro_san_version": neuro_san_version,
            "host": self._args.host,
            "agent": self._args.agent,
            "mode": "server-only",
            "expected_requests": expected,
            "received_requests": received,
            "peak_cpu_cores": peak_cpu_cores,
            "peak_memory_gb": peak_memory_gigabytes,
            "time_to_first_completed_s": first_completed_seconds,
            "avg_duration_s": avg_duration_seconds,
            "wall_time_s": wall_time_seconds,
        }
        return record

    @staticmethod
    def _add_server_log_findings(record: Dict[str, Any], round_record: Dict[str, Any]) -> None:
        """
        Add the round's server errors and tool warnings, each with its count, to the trend record.

        :param record: The trend record to add the 4 keys to
        :param round_record: The server-only round; its "server_errors" and "tool_warnings" lists, or None
        """
        errors: List[Dict[str, str]] = round_record.get("server_errors") or []
        warnings: List[Dict[str, str]] = round_record.get("tool_warnings") or []
        error_count: int = len(errors)
        warning_count: int = len(warnings)
        record["server_error_count"] = error_count
        record["tool_warning_count"] = warning_count
        record["server_errors"] = errors
        record["tool_warnings"] = warnings

    @staticmethod
    def _positive_durations(pairs: List[Dict[str, Any]]) -> List[float]:
        """
        Collect the positive server-side duration of each primary request.

        :param pairs: Primary agent Start/Finish pairs with "duration_seconds"
        :return: The durations in seconds that are numbers above 0, in pair order
        """
        durations_seconds: List[float] = []
        pair: Dict[str, Any]
        # Keep each numeric duration above 0.
        for pair in pairs:
            pair_duration: Any = pair.get("duration_seconds")
            if not isinstance(pair_duration, (int, float)):
                continue
            pair_duration_seconds: float = float(pair_duration)
            if pair_duration_seconds > 0:
                durations_seconds.append(pair_duration_seconds)
        return durations_seconds

    @staticmethod
    def _peak_cpu_cores(round_record: Dict[str, Any]) -> float:
        """
        Turn the round's peak system CPU percent into CPU cores in use.

        :param round_record: The server-only round; its "peak_system_cpu_percent" is over all cores, or None
            (counts as 0)
        :return: Cores in use, rounded to 2 decimals
        """
        peak_system_cpu_percent: Optional[float] = round_record.get("peak_system_cpu_percent")
        cpu_percent: float = peak_system_cpu_percent or 0.0
        core_count: int = cpu_count() or 1
        cores_in_use: float = ResourceMonitor.cores_in_use(cpu_percent, core_count)
        peak_cpu_cores: float = round(cores_in_use, 2)
        return peak_cpu_cores

    @staticmethod
    def _peak_memory_gigabytes(round_record: Dict[str, Any]) -> Optional[float]:
        """
        Turn the round's peak server RSS into gigabytes.

        :param round_record: The server-only round; its "peak_server" is a snapshot with "rss_megabytes", or None
        :return: Peak RSS in GB rounded to 2 decimals, or None when there is no snapshot
        """
        peak_server: Optional[Dict[str, Any]] = round_record.get("peak_server")
        if not peak_server:
            return None
        peak_rss_megabytes: float = peak_server.get("rss_megabytes", 0.0)
        peak_gigabytes: float = peak_rss_megabytes / ResourceMonitor.MEGABYTES_PER_GIGABYTE
        peak_memory_gigabytes: float = round(peak_gigabytes, 2)
        return peak_memory_gigabytes

    def _write_record(self, record: Dict[str, Any], successful: bool) -> None:
        """
        Append one JSON record to the trend-history file.

        :param record: The trend record
        :param successful: True for the trend file of good runs, False for history_unknown.jsonl
        """
        path: str = self.get_history_path(successful=successful)
        try:
            history_dir: str = dirname(path) or "."
            makedirs(history_dir, exist_ok=True)
            record_line: str = dumps(record) + "\n"
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(record_line)
            self.logger.info("  Trend history appended: %s", path)
        except OSError as exc:
            # Caught-exception text goes through a SensitiveLogger; when LEAF_LOG_SENSITIVE is off, the plain
            # logger still names the file.
            sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)
            if sensitive_logger.should_log():
                sensitive_logger.warning("  Could not write trend history to %s: %s", path, exc)
            else:
                self.logger.warning("  Could not write trend history to %s", path)

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
            if result.get("status") != LoadTestConstants.STATUS_CREATED:
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
        for threshold_seconds in LoadTestConstants.HISTORY_THRESHOLDS_SECONDS:
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
