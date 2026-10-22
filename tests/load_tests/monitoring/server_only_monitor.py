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

# gzip.open and re.compile stay module-qualified: a specific import would hide the builtins open and compile.
import gzip
import re
from argparse import Namespace
from json import dump
from logging import FileHandler
from logging import Formatter
from logging import INFO
from logging import Logger
from logging import getLogger
from os import makedirs
from os.path import getsize
from os.path import isfile
from os.path import join
from platform import platform
from platform import python_version
from re import Pattern
from shutil import copyfileobj
from socket import gethostname
from time import strftime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from psutil import Process
from psutil import cpu_count
from psutil import cpu_percent
from psutil import virtual_memory

from tests.load_tests.load_test_constants import RAW_RESULTS_FILE_NAME
from tests.load_tests.load_test_constants import SERVER_LOG_GZ_FILE_NAME
from tests.load_tests.load_test_constants import STDOUT_LOG_FILE_NAME
from tests.load_tests.monitoring.kernel_memory import KernelMemory
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.monitoring.server_log_tailer import ServerLogTailer
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.history_recorder import HistoryRecorder
from tests.load_tests.reporting.latency_analyzer import COMPLETION_MILESTONES
from tests.load_tests.reporting.latency_analyzer import LatencyAnalyzer
from tests.load_tests.reporting.run_namer import RunNamer
from tests.load_tests.reporting.summary import SummaryReporter
from tests.load_tests.reporting.system_resources import SystemResources
from tests.load_tests.validation.output_validator import OutputValidator
from tests.load_tests.validation.server_checker import ServerChecker


class ServerOnlyMonitor:
    """
    Runs --server-only mode: asks how many requests the client will send, follows the server log until they
    finish, then reports the round, writes raw_results.json and the history record, and asks again.
    """

    # 45 box-drawing "─" characters: the line around the end-of-round message.
    ROUND_END_LINE: str = "─────────────────────────────────────────────"
    ONE_HUNDRED_PERCENT: float = 100.0
    CPU_SAMPLE_SECONDS: float = 0.1

    def __init__(self, args: Namespace, profile: AgentProfile, monitor_parts: Dict[str, Any]) -> None:
        """
        Store what the server-only rounds use.

        :param args: Parsed command-line arguments
        :param profile: Agent profile with the primary agent's Start and Finish patterns
        :param monitor_parts: A dict with "server_process" (the local server process, or None when it is not
            found), "log_monitor" (monitor of the server log), "history_recorder" (writes the history record of
            each round) and "server_checker" (gives the neuro-san version to tag each round with)
        """
        server_process: Optional[Process] = monitor_parts.get("server_process")
        self.args: Namespace = args
        self.profile: AgentProfile = profile
        self.log_monitor: Optional[ServerLogMonitor] = monitor_parts.get("log_monitor")
        self.history_recorder: HistoryRecorder = monitor_parts.get("history_recorder")
        self.server_checker: ServerChecker = monitor_parts.get("server_checker")
        self.server_log_tailer: ServerLogTailer = ServerLogTailer(args, server_process, self.log_monitor)
        self.logger: Logger = getLogger(__name__)

    def run(self, output_base: str) -> int:
        """
        Interactive server-only monitoring loop.

        Prompts the user for the expected request count, then
        monitors the server log until all requests arrive (or
        timeout / Ctrl-C).  After each round, reports results,
        writes raw_results.json, archives the server log, and
        loops back for another round.  Only exits on Ctrl-C
        at the prompt.

        :param output_base: Base output directory; each round goes under its "server_only" folder
        :return: 0 when the user exits at the prompt
        """
        primary_start_pattern: str = self.profile.get_primary_start_pattern()
        primary_finish_pattern: str = self.profile.get_primary_finish_pattern()
        round_settings: Dict[str, Any] = {
            "primary_start_regex": re.compile(primary_start_pattern),
            "primary_finish_regex": re.compile(primary_finish_pattern),
            "output_base": output_base,
        }
        round_number: int = 0

        answer: str = ""
        expected_count: int = 0
        while True:
            try:
                answer = input("\nHow many requests will the client send? ")
            except (KeyboardInterrupt, EOFError):
                self.logger.info("\n  Exiting server-only monitor.")
                return 0

            answer = answer.strip()
            if not answer:
                continue
            try:
                expected_count = int(answer)
            except ValueError:
                self.logger.error("  Invalid number: %s", answer)
                continue
            if expected_count <= 0:
                self.logger.error("  Number must be positive.")
                continue

            round_number += 1
            self._run_server_only_round(round_settings, expected_count, round_number)

    def _run_server_only_round(self, round_settings: Dict[str, Any], expected_count: int, round_number: int) -> None:
        """
        Execute one round of server-only monitoring.

        Wraps the round body with a per-round ``stdout.log`` file
        handler so each server-only round captures its own console
        output (heartbeats + summary) in its output directory.

        :param round_settings: A dict with "primary_start_regex", "primary_finish_regex" (compiled patterns for
            the primary agent's Start and Finish lines) and "output_base" (base output directory)
        :param expected_count: Number of requests the client will send
        :param round_number: Round number, starting at 1
        """
        output_base: str = round_settings.get("output_base")
        round_dir: str = self._setup_round_output_dir(expected_count, output_base)
        log_position: Optional[int] = self.log_monitor.read_position()
        round_log_path: str = join(round_dir, STDOUT_LOG_FILE_NAME)
        round_handler: FileHandler = FileHandler(round_log_path, encoding="utf-8")
        round_handler.setLevel(INFO)
        message_formatter: Formatter = Formatter("%(message)s")
        round_handler.setFormatter(message_formatter)
        root_logger: Logger = getLogger()
        root_logger.addHandler(round_handler)
        round_values: Dict[str, Any] = {}
        try:
            round_values = {
                "expected": expected_count,
                "round_number": round_number,
                "primary_start_regex": round_settings.get("primary_start_regex"),
                "primary_finish_regex": round_settings.get("primary_finish_regex"),
                "round_dir": round_dir,
                "log_position": log_position,
                "round_log_path": round_log_path,
            }
            self._server_only_round_body(round_values)
        finally:
            root_logger.removeHandler(round_handler)
            round_handler.close()

    def _setup_round_output_dir(self, expected_count: int, output_base: str) -> str:
        """
        Create an output directory for a server-only round.

        :param expected_count: Number of requests the client will send, for the folder name
        :param output_base: Base output directory; the round goes under its "server_only" folder
        :return: Path of the round output directory
        """
        timestamp: str = strftime("%Y%m%d_%H%M%S")
        neuro_san_version: Optional[str] = self.server_checker.resolve_ns_version()
        folder_name: str = RunNamer.run_folder_name(timestamp, self.args.host, neuro_san_version, expected_count)
        round_dir: str = join(output_base, "server_only", folder_name)
        makedirs(round_dir, exist_ok=True)
        return round_dir

    def _server_only_round_body(self, round_values: Dict[str, Any]) -> None:
        """
        Run the steps of one server-only round: snapshots, log tailing, reports, raw_results.json and the
        server log copy.

        :param round_values: A dict with "expected" (requests the client will send), "round_number" (starting at
                             1), "primary_start_regex", "primary_finish_regex" (compiled patterns for the
                             primary agent's Start and Finish lines), "round_dir" (output directory of the
                             round), "log_position" (server log position at the start of the round) and
                             "round_log_path" (path of the round's stdout.log)
        """
        expected_count: int = round_values.get("expected")
        round_number: int = round_values.get("round_number")
        round_dir: str = round_values.get("round_dir")
        self._log_round_header(round_number, expected_count)
        before_values: Dict[str, Any] = self._log_before_round()

        self.logger.info(
            """
Waiting for %d request(s) in server log...
  Start the client on the remote machine now.""",
            expected_count,
        )

        tail_inputs: Dict[str, Any] = {
            "expected": expected_count,
            "log_position": round_values.get("log_position"),
            "primary_start_regex": round_values.get("primary_start_regex"),
            "primary_finish_regex": round_values.get("primary_finish_regex"),
            "before_server": before_values.get("before_server"),
            "before_system_memory_percent": before_values.get("before_system_memory_percent"),
        }
        tail_result: Dict[str, Any] = self.server_log_tailer.tail_server_log(tail_inputs)
        received_count: int = tail_result.get("count")
        completed_count: int = tail_result.get("completed")
        elapsed_seconds: float = tail_result.get("elapsed_seconds")

        self.logger.info(
            "\n  Monitoring complete: %d/%d received, %d/%d processed in %.1fs",
            received_count, expected_count, completed_count,
            received_count, elapsed_seconds,
        )

        after_values: Dict[str, Any] = self._log_after_round(before_values, tail_result)
        self._record_round(round_values, before_values, tail_result, after_values)

        self._archive_server_log_to(round_dir)

        round_log_path: str = round_values.get("round_log_path")
        self._log_output_files(round_dir, round_log_path)

        self.logger.info("\n%s", ServerOnlyMonitor.ROUND_END_LINE)
        self.logger.info("  Round %d complete. Ready for next round.", round_number)
        self.logger.info("%s", ServerOnlyMonitor.ROUND_END_LINE)

    def _log_round_header(self, round_number: int, expected_count: int) -> None:
        """
        Log the round number, the expected requests and the neuro-san version.

        :param round_number: Round number, starting at 1
        :param expected_count: Number of requests the client will send
        """
        self.logger.info("\n%s", Formatters.SEPARATOR_LINE)
        self.logger.info("  Round %d: expecting %d request(s)", round_number, expected_count)
        self.logger.info(Formatters.SEPARATOR_LINE)
        version_text: str = "unknown"
        resolved_version: Optional[str] = self.server_checker.resolve_ns_version()
        if resolved_version:
            version_text = resolved_version
        self.logger.info("  neuro-san version: %s", version_text)

    def _log_before_round(self) -> Dict[str, Any]:
        """
        Log the server and system resources before the round.

        :return: Dict with "before_server" (server snapshot, or None), "before_system_memory_percent" and
            "system_before" (the system values SystemResources.log_section() reads)
        """
        before_server: Optional[Dict[str, Any]] = self.server_log_tailer.snapshot_server()
        if before_server:
            ResourceMonitor.log_snapshot("Server BEFORE", before_server)
        # psutil.virtual_memory() returns psutil's private svmem named tuple, which has no public type to name.
        before_memory_stats: Any = virtual_memory()
        before_used_bytes: int = before_memory_stats.total - before_memory_stats.available
        before_used_megabytes: float = before_used_bytes / ResourceMonitor.ONE_MEGABYTE
        before_available_gigabytes: float = before_memory_stats.available / ResourceMonitor.ONE_GIGABYTE
        total_gigabytes: float = before_memory_stats.total / ResourceMonitor.ONE_GIGABYTE
        self.logger.info(
            "  System BEFORE: %.0f%% used (%.0fM used / %.1fG free / %.1fG total)",
            before_memory_stats.percent, before_used_megabytes,
            before_available_gigabytes, total_gigabytes,
        )
        core_count: int = 1
        logical_core_count: Optional[int] = cpu_count()
        if logical_core_count:
            core_count = logical_core_count
        before_system_cpu_percent: float = cpu_percent(interval=ServerOnlyMonitor.CPU_SAMPLE_SECONDS)
        self.logger.info("  System CPU: %d cores (%.0f%% in use)", core_count, before_system_cpu_percent)
        before_system_threads: int = SystemResources.total_threads()
        user_limit: str = ""
        system_thread_max: str = ""
        user_limit, system_thread_max = SystemResources.thread_limits()
        self.logger.info(
            "  System threads: %s in use / limit %s per-user (%s max)",
            f"{before_system_threads:,}", user_limit, system_thread_max,
        )
        before_values: Dict[str, Any] = {
            "before_server": before_server,
            "before_system_memory_percent": before_memory_stats.percent,
            "system_before": {
                "mem_pct": before_memory_stats.percent,
                "mem_avail_gb": before_available_gigabytes,
                "cpu_pct": before_system_cpu_percent,
                "threads": before_system_threads,
            },
        }
        return before_values

    def _log_after_round(self, before_values: Dict[str, Any], tail_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Log the system resources before, at the peak of and after the round.

        :param before_values: The dict _log_before_round() returns
        :param tail_result: The dict ServerLogTailer.tail_server_log() returns
        :return: Dict with "after_server" (server snapshot, or None), "after_kernel" (kernel memory, or None)
            and "after_system_memory_percent"
        """
        after_server: Optional[Dict[str, Any]] = self.server_log_tailer.snapshot_server()
        after_kernel: Optional[Dict[str, float]] = KernelMemory.read_kernel_memory()
        # psutil.virtual_memory() returns psutil's private svmem named tuple, which has no public type to name.
        after_memory_stats: Any = virtual_memory()
        total_gigabytes: float = after_memory_stats.total / ResourceMonitor.ONE_GIGABYTE
        after_available_gigabytes: float = after_memory_stats.available / ResourceMonitor.ONE_GIGABYTE
        after_system_cpu_percent: float = cpu_percent(interval=ServerOnlyMonitor.CPU_SAMPLE_SECONDS)
        after_system_threads: int = SystemResources.total_threads()
        system_before: Dict[str, float] = before_values.get("system_before")
        system_peak: Dict[str, float] = ServerOnlyMonitor._system_peak(tail_result, total_gigabytes)
        SystemResources.log_section(
            system_before,
            system_peak,
            {
                "mem_pct": after_memory_stats.percent,
                "mem_avail_gb": after_available_gigabytes,
                "cpu_pct": after_system_cpu_percent,
                "threads": after_system_threads,
            },
        )
        after_values: Dict[str, Any] = {
            "after_server": after_server,
            "after_kernel": after_kernel,
            "after_system_memory_percent": after_memory_stats.percent,
        }
        return after_values

    @staticmethod
    def _system_peak(tail_result: Dict[str, Any], total_gigabytes: float) -> Dict[str, float]:
        """
        Build the peak system values that SystemResources.log_section() reads.

        :param tail_result: The dict ServerLogTailer.tail_server_log() returns
        :param total_gigabytes: Total system memory in GB
        :return: Dict with "mem_pct", "mem_avail_gb", "cpu_pct" (None when not sampled) and "threads"
        """
        peak_system_memory_percent: float = tail_result.get("peak_sys_mem_pct")
        peak_used_fraction: float = peak_system_memory_percent / ServerOnlyMonitor.ONE_HUNDRED_PERCENT
        peak_available_gigabytes: float = total_gigabytes - peak_used_fraction * total_gigabytes
        system_peak: Dict[str, float] = {
            "mem_pct": peak_system_memory_percent,
            "mem_avail_gb": peak_available_gigabytes,
            "cpu_pct": tail_result.get("peak_sys_cpu_percent"),
            "threads": tail_result.get("peak_sys_threads"),
        }
        return system_peak

    def _record_round(self, round_values: Dict[str, Any], before_values: Dict[str, Any],
                      tail_result: Dict[str, Any], after_values: Dict[str, Any]) -> None:
        """
        Log the round's percentiles, server errors and token usage, then write raw_results.json and the history
        record.

        :param round_values: The dict _server_only_round_body() gets
        :param before_values: The dict _log_before_round() returns
        :param tail_result: The dict ServerLogTailer.tail_server_log() returns
        :param after_values: The dict _log_after_round() returns
        """
        expected_count: int = round_values.get("expected")
        log_position: Optional[int] = round_values.get("log_position")
        received_count: int = tail_result.get("count")
        elapsed_seconds: float = tail_result.get("elapsed_seconds")
        peak_server: Optional[Dict[str, Any]] = tail_result.get("peak_server")
        primary_start_regex: Pattern = round_values.get("primary_start_regex")
        primary_pairs: List[Dict[str, Any]] = self.server_log_tailer.server_only_primary_pairs(log_position,
                                                                                               primary_start_regex)
        self._log_server_completion_percentiles(primary_pairs)

        server_errors: List[Dict[str, str]] = self.log_monitor.scan_server_errors_since(log_position)
        OutputValidator.log_server_errors(server_errors)
        tool_warnings: List[Dict[str, str]] = self.log_monitor.scan_tool_warnings_since(log_position)
        OutputValidator.log_tool_warnings(tool_warnings)

        self._log_server_only_token_usage(log_position)

        round_results: Dict[str, Any] = {
            "round_dir": round_values.get("round_dir"),
            "expected": expected_count,
            "count": received_count,
            "elapsed_seconds": elapsed_seconds,
            "before_server": before_values.get("before_server"),
            "after_server": after_values.get("after_server"),
            "peak_server": peak_server,
            "peak_threads": tail_result.get("peak_threads"),
            "before_system_memory_percent": before_values.get("before_system_memory_percent"),
            "peak_system_memory_percent": tail_result.get("peak_sys_mem_pct"),
            "after_system_memory_percent": after_values.get("after_system_memory_percent"),
            "interrupted": tail_result.get("interrupted"),
            "kernel_breakdown": ServerOnlyMonitor._round_kernel_breakdown(peak_server, after_values),
            "avg_system_cpu_percent": tail_result.get("avg_sys_cpu_percent"),
            "peak_system_cpu_percent": tail_result.get("peak_sys_cpu_percent"),
            "server_errors": server_errors,
            "tool_warnings": tool_warnings,
        }
        self._export_server_only_json(round_results)
        self._append_history_record(round_results, primary_pairs)

    def _append_history_record(self, round_results: Dict[str, Any], primary_pairs: List[Dict[str, Any]]) -> None:
        """
        Append the round's record to the server history file.

        :param round_results: The dict _export_server_only_json() gets
        :param primary_pairs: Primary-agent Start/Finish pairs of the round
        """
        server_ns_version: Optional[str] = self.server_checker.get_server_ns_version()
        expected_count: int = round_results.get("expected")
        received_count: int = round_results.get("count")
        elapsed_seconds: float = round_results.get("elapsed_seconds")
        peak_server: Optional[Dict[str, Any]] = round_results.get("peak_server")
        peak_system_cpu_percent: float = round_results.get("peak_system_cpu_percent")
        server_errors: List[Dict[str, str]] = round_results.get("server_errors")
        tool_warnings: List[Dict[str, str]] = round_results.get("tool_warnings")
        self.history_recorder.append_server_record(
            server_ns_version, expected_count, received_count, elapsed_seconds, peak_server, peak_system_cpu_percent,
            primary_pairs, server_errors, tool_warnings,
        )

    @staticmethod
    def _round_kernel_breakdown(peak_server: Optional[Dict[str, Any]],
                                after_values: Dict[str, Any]) -> Dict[str, float]:
        """
        Work out the round's kernel memory breakdown without logging it.

        :param peak_server: Peak server snapshot, or None
        :param after_values: The dict _log_after_round() returns
        :return: The kernel memory breakdown, sized against the peak server RSS (or the after-round RSS)
        """
        after_server: Optional[Dict[str, Any]] = after_values.get("after_server")
        after_kernel: Optional[Dict[str, float]] = after_values.get("after_kernel")
        peak_rss_megabytes: float = 0.0
        if peak_server:
            peak_rss_megabytes = peak_server.get("rss", 0)
        elif after_server:
            peak_rss_megabytes = after_server.get("rss", 0)
        kernel_breakdown: Dict[str, float] = KernelMemory.kernel_breakdown(after_kernel, peak_rss_megabytes, log=False)
        return kernel_breakdown

    def _log_output_files(self, round_dir: str, round_log_path: str) -> None:
        """
        Log the round's OUTPUT FILES section.

        :param round_dir: Output directory of the round
        :param round_log_path: Path of the round's stdout.log
        """
        self.logger.info("\n%s", Formatters.SEPARATOR_LINE)
        self.logger.info("  OUTPUT FILES")
        self.logger.info(Formatters.SEPARATOR_LINE)
        self.logger.info("  Directory:   %s", round_dir)
        json_path: str = join(round_dir, RAW_RESULTS_FILE_NAME)
        if isfile(json_path):
            self.logger.info("  Raw results: %s", json_path)
        gz_path: str = join(round_dir, SERVER_LOG_GZ_FILE_NAME)
        size_megabytes: float = 0.0
        if isfile(gz_path):
            size_megabytes = getsize(gz_path) / ResourceMonitor.ONE_MEGABYTE
            self.logger.info("  Server log:  %s (%.1fM)", gz_path, size_megabytes)
        self.logger.info("  Stdout log:  %s", round_log_path)
        self.history_recorder.log_existing_history_files()

    def _log_server_only_token_usage(self, log_position: Optional[int]) -> None:
        """
        Log the LLM & TOKEN USAGE section for a server-only round.

        There is no client side in server-only, so the client line
        reads "not available" and the numbers come solely from
        server.log token accounting.

        :param log_position: Server log position at the start of the round
        """
        token_data: Dict[str, Dict[str, Any]] = self.log_monitor.parse_token_accounting_since(log_position)
        token_entries: List[Dict[str, Any]] = []
        token_entry: Dict[str, Any]
        # Collect the token entry of each request.
        for token_entry in token_data.values():
            token_entries.append(token_entry)
        server_stats: Optional[Dict[str, int]] = SummaryReporter.aggregate_token_entries(token_entries)
        printed: bool = SummaryReporter.render_token_usage(None, server_stats, client_source="HTTP token_accounting")
        if not printed:
            return
        model_counts: Dict[str, int] = {}
        model: Optional[str] = None
        entry: Dict[str, Any]
        # Count the requests of each known model.
        for entry in token_data.values():
            model = entry.get("model")
            if model and model != "unknown":
                model_counts[model] = model_counts.get(model, 0) + 1
        model_names: List[str] = []
        model_texts: List[str] = []
        request_count: int = 0
        models_text: str = ""
        if model_counts:
            model_names = []
            model_name: str
            # Collect the model names, then put the most used first.
            for model_name in model_counts.keys():
                model_names.append(model_name)
            model_names.sort(key=model_counts.get, reverse=True)
            model_texts = []
            # Show each model with its request count.
            for model_name in model_names:
                request_count = model_counts.get(model_name)
                model_texts.append(f"{model_name} ({request_count})")
            models_text = ", ".join(model_texts)
            self.logger.info("  LLM models: %s", models_text)

    def _log_server_completion_percentiles(self, primary_pairs: List[Dict[str, Any]]) -> None:
        """
        Log server-side completion-duration percentiles on one line.

        Durations are server-side processing times (Start->Finish from
        the primary agent's log pairs), so they run slightly shorter
        than the client's end-to-end per-request duration.  Reuses
        ``LatencyAnalyzer.percentile`` and ``COMPLETION_MILESTONES`` so
        the math and labels match the client's percentile line.

        :param primary_pairs: Primary-agent Start/Finish pairs, each with ``duration_seconds``
        """
        positive_durations: List[float] = ServerLogTailer.positive_durations(primary_pairs)
        durations: List[float] = sorted(positive_durations)
        if not durations:
            return
        milestone_texts: List[str] = []
        percentile_seconds: float = 0.0
        percentile_text: str = ""
        milestone_percent: int
        # Format each completion milestone, e.g. "p50 1.2s".
        for milestone_percent in COMPLETION_MILESTONES:
            percentile_seconds = LatencyAnalyzer.percentile(durations, milestone_percent)
            percentile_text = Formatters.fmt_duration(percentile_seconds, precision=1)
            milestone_texts.append(f"p{milestone_percent} {percentile_text}")
        milestones_text: str = " / ".join(milestone_texts)
        request_count: int = len(durations)
        self.logger.info("\n  Server-side completion percentiles (%d requests): %s", request_count, milestones_text)

    def _export_server_only_json(self, round_results: Dict[str, Any]) -> None:
        """
        Write raw_results.json for a server-only round.

        :param round_results: A dict with "round_dir", "expected", "count", "elapsed_seconds",
                              "before_server", "after_server", "peak_server" (server process snapshots, or None),
                              "peak_threads", "before_system_memory_percent", "peak_system_memory_percent",
                              "after_system_memory_percent", "interrupted" (True when Ctrl-C stops the round),
                              "kernel_breakdown", "avg_system_cpu_percent", "peak_system_cpu_percent",
                              "server_errors" and "tool_warnings" (each may be None)
        """
        round_dir: str = round_results.get("round_dir")
        elapsed_seconds: float = round_results.get("elapsed_seconds")
        server_cpu_values: Dict[str, Optional[float]] = ServerOnlyMonitor._server_cpu_values(round_results)
        server_errors: Optional[List[Dict[str, str]]] = round_results.get("server_errors")
        tool_warnings: Optional[List[Dict[str, str]]] = round_results.get("tool_warnings")
        kernel_breakdown: Optional[Dict[str, float]] = round_results.get("kernel_breakdown")
        raw_data: Dict[str, Any] = {
            "test_metadata": {
                "timestamp": strftime("%Y-%m-%dT%H:%M:%S%z"),
                "hostname": gethostname(),
                "python_version": python_version(),
                "platform": platform(),
                "mode": "server-only",
                "agent": self.args.agent,
            },
            "round": {
                "expected_requests": round_results.get("expected"),
                "received_requests": round_results.get("count"),
                "elapsed_seconds": round(elapsed_seconds, 2),
                "interrupted": round_results.get("interrupted"),
            },
            "server_resources": {
                "before": round_results.get("before_server"),
                "after": round_results.get("after_server"),
                "peak": round_results.get("peak_server"),
                "peak_threads": round_results.get("peak_threads"),
            },
            "system_memory": {
                "before_pct": round_results.get("before_system_memory_percent"),
                "peak_pct": round_results.get("peak_system_memory_percent"),
                "after_pct": round_results.get("after_system_memory_percent"),
            },
            "system_cpu": {
                "avg_pct": round_results.get("avg_system_cpu_percent"),
                "peak_pct": round_results.get("peak_system_cpu_percent"),
                "server_cpu_seconds_total": server_cpu_values.get("server_cpu_seconds_total"),
                "server_cpu_seconds_per_request": server_cpu_values.get("server_cpu_seconds_per_request"),
            },
        }
        server_error_list: List[Dict[str, str]] = []
        if server_errors:
            server_error_list = server_errors
        tool_warning_list: List[Dict[str, str]] = []
        if tool_warnings:
            tool_warning_list = tool_warnings
        raw_data["server_errors"] = server_error_list
        raw_data["tool_warnings"] = tool_warning_list
        if kernel_breakdown:
            raw_data["kernel_memory_breakdown"] = kernel_breakdown
        json_path: str = join(round_dir, RAW_RESULTS_FILE_NAME)
        with open(json_path, "w", encoding="utf-8") as json_file:
            dump(raw_data, json_file, indent=2)

    @staticmethod
    def _server_cpu_values(round_results: Dict[str, Any]) -> Dict[str, Optional[float]]:
        """
        Work out the server CPU seconds used in the round, in total and per received request.

        :param round_results: The dict _export_server_only_json() gets, with "before_server", "after_server"
            (server snapshots with "cpu_seconds", or None) and "count" (requests received)
        :return: Dict with "server_cpu_seconds_total" and "server_cpu_seconds_per_request", each None when
            unknown
        """
        before_server: Optional[Dict[str, Any]] = round_results.get("before_server")
        after_server: Optional[Dict[str, Any]] = round_results.get("after_server")
        received_count: int = round_results.get("count")
        server_cpu_seconds: Optional[float] = None
        cpu_before: Optional[float] = None
        cpu_after: Optional[float] = None
        if before_server and after_server:
            cpu_before = before_server.get("cpu_seconds")
            cpu_after = after_server.get("cpu_seconds")
            if cpu_before is not None and cpu_after is not None:
                server_cpu_seconds = cpu_after - cpu_before
        server_cpu_seconds_per_request: Optional[float] = None
        if server_cpu_seconds is not None and received_count > 0:
            server_cpu_seconds_per_request = server_cpu_seconds / received_count
        server_cpu_values: Dict[str, Optional[float]] = {
            "server_cpu_seconds_total": server_cpu_seconds,
            "server_cpu_seconds_per_request": server_cpu_seconds_per_request,
        }
        return server_cpu_values

    def _archive_server_log_to(self, target_dir: str) -> None:
        """
        Gzip the server log into the given directory.

        :param target_dir: Directory for the gzipped server log
        """
        server_log: Optional[str] = self.args.server_log
        if not server_log or not isfile(server_log):
            return
        gz_path: str = join(target_dir, SERVER_LOG_GZ_FILE_NAME)
        with open(server_log, "rb") as source_file, gzip.open(gz_path, "wb") as gzip_file:
            copyfileobj(source_file, gzip_file)
