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

from argparse import Namespace
from logging import Logger
from logging import getLogger
from threading import Event
from threading import Thread
from time import localtime
from time import perf_counter
from time import strftime
from time import struct_time
from time import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from psutil import AccessDenied
from psutil import NoSuchProcess
from psutil import Process

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.reporting.duration_parser import DurationParser
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.sensitive_error_logger import SensitiveErrorLogger
from tests.load_tests.reporting.stage_data_collector import StageDataCollector
from tests.load_tests.reporting.stage_summary_builder import StageSummaryBuilder
from tests.load_tests.reporting.system_resources import SystemResources
from tests.load_tests.traffic.runner import TrafficRunner
from tests.load_tests.traffic.stage_plan import StagePlan
from tests.load_tests.validation.output_validator import OutputValidator


class StageExecutor:
    """
    Runs one stage of a load test and builds its summary dict, and checks --total-timeout.
    StageRun runs the stages round by round.
    """

    def __init__(self, args: Namespace, runner: TrafficRunner, executor_parts: Dict[str, Any]) -> None:
        """
        Keep the run's arguments, the traffic runner and the parts each stage needs.

        :param args: Parsed command-line arguments
        :param runner: Traffic runner that sends the requests of a stage
        :param executor_parts: A dict with "profile" (the AgentProfile), "log_monitor" (the ServerLogMonitor, or
            None), "resource_reporter" (the ResourceReporter), "server_process" (the local server process, or None)
            and "output_dir" (the run's output directory)
        """
        class_logger: Logger = getLogger(self.__class__.__name__)
        self.logger: SensitiveErrorLogger = SensitiveErrorLogger(class_logger)
        self.args: Namespace = args
        self.runner: TrafficRunner = runner
        self.log_monitor: Optional[ServerLogMonitor] = executor_parts.get("log_monitor")
        self.server_process: Optional[Process] = executor_parts.get("server_process")
        self._output_dir: Optional[str] = executor_parts.get("output_dir")
        collector_parts: Dict[str, Any] = {
            "profile": executor_parts.get("profile"),
            "log_monitor": self.log_monitor,
            "resource_reporter": executor_parts.get("resource_reporter"),
            "server_process": self.server_process,
            "output_dir": self._output_dir,
        }
        self._data_collector: StageDataCollector = StageDataCollector(args, collector_parts)

    def total_timeout_reached(self, test_start_seconds: float) -> bool:
        """
        Check if total-timeout has been exceeded.

        Logs a warning when the elapsed time since
        test_start_seconds reaches --total-timeout (0 means disabled).

        :param test_start_seconds: perf_counter() at the start of the test
        :return: True when the total timeout is reached
        """
        limit_seconds: float = self.args.total_timeout
        if limit_seconds <= 0:
            return False
        elapsed_seconds: float = perf_counter() - test_start_seconds
        if elapsed_seconds < limit_seconds:
            return False
        elapsed_text: str = DurationParser.format_minutes_seconds(elapsed_seconds)
        self.logger.warning(
            """
  ABORT: --total-timeout (%ss) reached after %s.
  Stopping test and reporting available results.""",
            limit_seconds, elapsed_text,
        )
        return True

    def run_single_stage(self, stage_inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute one stage of the load test.

        :param stage_inputs: A dictionary with "actual_requests" (number of requests to send in this stage),
            "num_concurrent" (requested concurrency before the --max-requests cap), "stage_num" and "round_num"
            (starting at 1), "global_offset" (number of requests sent by earlier stages), "monitor_resources" (True to
            take resource snapshots around the stage), "has_server_log" (True when the server log can be read),
            "probe_result" (result of the dry-run probe to count in this stage, or None), "only_stage" (True when
            this is the only stage) and "primary_start_pattern" (server log pattern of a primary request start)
        :return: Dict with "summary" (the stage summary dict), "probe_used" (True when probe_result was counted),
            "should_abort" (True when the test must stop after this stage) and "interrupted" (True when Ctrl-C
            stops the stage)
        """
        stage_start: Dict[str, Any] = self._start_stage(stage_inputs)
        stage_run: Dict[str, Any] = self._fire_stage(stage_inputs, stage_start)
        stage_check: Dict[str, Any] = self._check_stage(stage_inputs, stage_start, stage_run)
        post_stage_data: Dict[str, Any] = {}
        if not stage_check.get("should_abort"):
            post_stage_data = self._collect_after_stage(stage_inputs, stage_start, stage_run, stage_check)
        system_before: Dict[str, Optional[float]] = stage_run.get("system_before")
        system_after: Dict[str, Optional[float]] = SystemResources.snapshot()
        stage_values: Dict[str, Any] = {
            "stage_num": stage_inputs.get("stage_num"),
            "round_num": stage_inputs.get("round_num"),
            "actual_requests": stage_inputs.get("actual_requests"),
            "counts": stage_check.get("counts"),
            "elapsed_seconds": stage_run.get("total_time_seconds"),
            "retries": stage_check.get("retries"),
            "total_retries": stage_check.get("total_retries"),
            "amplification": stage_check.get("amplification"),
            "results": stage_run.get("results"),
            "has_server_log": stage_inputs.get("has_server_log"),
            "has_tokens": self.args.include_tokens,
            "monitor_resources": stage_inputs.get("monitor_resources"),
            "before_server": stage_start.get("before_server"),
            "peak_threads": stage_run.get("peak_server_threads"),
            "peak_server_rss_megabytes": stage_run.get("peak_server_rss_megabytes"),
            "before_client": stage_start.get("before_client"),
            "peak_client": stage_run.get("peak_client"),
            "settled_client": stage_run.get("settled_client"),
            "before_system_memory_percent": system_before.get("memory_percent"),
            "after_system_memory_percent": system_after.get("memory_percent"),
            "peak_system_memory": stage_run.get("peak_system_memory"),
            "peak_system_cpu_percent": stage_run.get("peak_system_cpu_percent"),
            "before_system": system_before,
            "after_system": system_after,
            "peak_system_threads": stage_run.get("peak_system_threads"),
        }
        server_log_values: Dict[str, Any] = StageExecutor._server_log_values(post_stage_data)
        stage_values.update(server_log_values)
        summary_entry: Dict[str, Any] = StageSummaryBuilder.build_stage_summary(stage_values)
        stage_result: Dict[str, Any] = {
            "summary": summary_entry,
            "probe_used": stage_start.get("probe_used"),
            "should_abort": stage_check.get("should_abort"),
            "interrupted": stage_run.get("interrupted"),
        }
        return stage_result

    def _stage_workers(self, stage_inputs: Dict[str, Any]) -> int:
        """
        Return the most worker threads a stage uses: its request count with --ramp, else --max-workers.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :return: Most worker threads the stage uses
        """
        stage_workers: int = self.args.max_workers
        if self.args.ramp:
            stage_workers = stage_inputs.get("actual_requests")
        return stage_workers

    def _log_stage_header(self, stage_inputs: Dict[str, Any], stage_workers: int) -> None:
        """
        Log the header of a stage: its request count, worker count and round.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :param stage_workers: Most worker threads the stage uses
        """
        actual_requests: int = stage_inputs.get("actual_requests")
        num_concurrent: int = stage_inputs.get("num_concurrent")
        stage_num: int = stage_inputs.get("stage_num")
        round_num: int = stage_inputs.get("round_num")
        self.logger.info("\n%s", Formatters.SEPARATOR_LINE)
        stage_label: str = f"{actual_requests} requests (max {stage_workers} workers)"
        if self.args.ramp:
            stage_label = f"[STAGE {stage_num}] {stage_label}"
        if self.args.num_rounds > 1:
            stage_label += f" (round {round_num})"
        self.logger.info("  %s", stage_label)
        self.logger.info("%s", Formatters.SEPARATOR_LINE)

        if actual_requests < num_concurrent:
            self.logger.info("  (Capped from %s to %s by --max-requests)", num_concurrent, actual_requests)

    def _start_stage(self, stage_inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Log the stage header and take the server log position and the resource snapshots before the stage.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :return: Dict with "stage_workers" (most worker threads), "log_position" (server log offset, or None),
            "client_process" (the client process, or None without resource monitoring), "before_server" and
            "before_client" (snapshots, or None), "stage_requests" (number of requests to fire, without the probe)
            and "probe_used" (True when the dry-run probe counts as the first request)
        """
        actual_requests: int = stage_inputs.get("actual_requests")
        monitor_resources: bool = stage_inputs.get("monitor_resources")
        probe_result: Optional[Dict[str, Any]] = stage_inputs.get("probe_result")
        stage_workers: int = self._stage_workers(stage_inputs)
        self._log_stage_header(stage_inputs, stage_workers)

        log_position: Optional[int] = None
        if stage_inputs.get("has_server_log"):
            log_position = self.log_monitor.read_position()

        client_process: Optional[Process] = None
        before_snapshots: Dict[str, Optional[Dict[str, Any]]] = {}
        if monitor_resources:
            client_process = Process()
            before_snapshots = self._capture_before_snapshots(client_process)

        self._log_fire_info(actual_requests, monitor_resources, probe_result)

        # If a dry-run probe ran, inject it into stage 1.  The probe
        # fired before log_position was captured, so only stage_requests of
        # them appear in the server log from here on.
        stage_requests: int = actual_requests
        probe_used: bool = probe_result is not None
        if probe_used:
            stage_requests = max(actual_requests - 1, 0)

        stage_start: Dict[str, Any] = {
            "stage_workers": stage_workers,
            "log_position": log_position,
            "client_process": client_process,
            "before_server": before_snapshots.get("server"),
            "before_client": before_snapshots.get("client"),
            "stage_requests": stage_requests,
            "probe_used": probe_used,
        }
        return stage_start

    def _fire_stage(self, stage_inputs: Dict[str, Any], stage_start: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fire the requests of a stage while the server log monitor runs, then take the client snapshots.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :param stage_start: The dict from _start_stage()
        :return: The stage run dict of TrafficRunner.run_stage(), with the probe counted in "results" and
            "total_time_seconds", plus "system_before" (system snapshot before the requests), "peak_client" (peak
            client RSS snapshot, or None) and "settled_client" (client snapshot after the stage, or None)
        """
        probe_result: Optional[Dict[str, Any]] = stage_inputs.get("probe_result")
        probe_used: bool = stage_start.get("probe_used")
        client_process: Optional[Process] = stage_start.get("client_process")
        stop_event: Event = Event()
        monitor: Optional[Thread] = None
        if stage_inputs.get("has_server_log"):
            monitor = self._start_log_monitor(stage_inputs, stage_start, stop_event)

        system_before: Dict[str, Optional[float]] = SystemResources.snapshot()

        first_request_number: int = stage_inputs.get("global_offset")
        # The dry-run probe is the first request of the stage.
        if probe_used:
            first_request_number += 1
        stage_requests: int = stage_start.get("stage_requests")
        stage_workers: int = stage_start.get("stage_workers")
        plan: StagePlan = StagePlan(stage_requests, stage_workers, first_request_number, self._output_dir)
        stage_run: Dict[str, Any] = self.runner.run_stage(plan, server_process=self.server_process,
                                                          client_process=client_process, log_monitor=self.log_monitor)
        if probe_used:
            StageExecutor._count_probe(stage_run, probe_result)

        stop_event.set()
        if monitor:
            monitor.join(timeout=LoadTestConstants.THREAD_JOIN_TIMEOUT_SECONDS)

        stage_run["system_before"] = system_before
        stage_run["peak_client"] = None
        stage_run["settled_client"] = None
        if stage_inputs.get("monitor_resources"):
            peak_client_rss_megabytes: Optional[float] = stage_run.get("peak_client_rss_megabytes")
            if peak_client_rss_megabytes is not None:
                stage_run["peak_client"] = {"rss_megabytes": peak_client_rss_megabytes}
            stage_run["settled_client"] = ResourceMonitor.snapshot(client_process)
        return stage_run

    @staticmethod
    def _count_probe(stage_run: Dict[str, Any], probe_result: Dict[str, Any]) -> None:
        """
        Count the dry-run probe as the first request of the stage.

        :param stage_run: The stage run dict of TrafficRunner.run_stage(); its "results" and "total_time_seconds"
            are updated here
        :param probe_result: The result of the dry-run probe
        """
        stage_results: List[Dict[str, Any]] = stage_run.get("results")
        stage_results.insert(0, probe_result)
        stage_time_seconds: float = stage_run.get("total_time_seconds")
        probe_time_seconds: float = probe_result.get("elapsed", 0.0)
        stage_run["total_time_seconds"] = stage_time_seconds + probe_time_seconds

    def _start_log_monitor(self, stage_inputs: Dict[str, Any], stage_start: Dict[str, Any],
                           stop_event: Event) -> Optional[Thread]:
        """
        Start the server log monitor thread of a stage.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :param stage_start: The dict from _start_stage()
        :param stop_event: Event that stops the monitor when the stage ends
        :return: The monitor thread, or None when the server log can't be read
        """
        monitor_start_seconds: float = perf_counter()
        primary_start_pattern: str = stage_inputs.get("primary_start_pattern")
        log_position: Optional[int] = stage_start.get("log_position")
        stage_requests: int = stage_start.get("stage_requests")
        client_process: Optional[Process] = stage_start.get("client_process")
        monitor_settings: Dict[str, Any] = {
            "position": log_position,
            "expected_count": stage_requests,
            "fire_time_seconds": monitor_start_seconds,
            "stop_event": stop_event,
            "client_process": client_process,
            "primary_start_pattern": primary_start_pattern,
            "output_dir": self._output_dir,
        }
        monitor: Optional[Thread] = self.log_monitor.start_log_monitor(monitor_settings)
        return monitor

    def _check_stage(self, stage_inputs: Dict[str, Any], stage_start: Dict[str, Any],
                     stage_run: Dict[str, Any]) -> Dict[str, Any]:
        """
        Count the results and the server retries of a stage, log them, and decide if the test must stop.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :param stage_start: The dict from _start_stage()
        :param stage_run: The dict from _fire_stage()
        :return: Dict with "counts" (result counts), "retries" (retry count per error type), "total_retries",
            "amplification" (server calls per request) and "should_abort" (True when the test must stop)
        """
        results: List[Dict[str, Any]] = stage_run.get("results")
        counts: Dict[str, Any] = OutputValidator.count_results(results)
        stage_retries: Dict[str, Any] = self._count_stage_retries(stage_inputs, stage_start)

        actual_requests: int = stage_inputs.get("actual_requests")
        total_time_seconds: float = stage_run.get("total_time_seconds")
        only_stage: bool = stage_inputs.get("only_stage", False)
        OutputValidator.log_stage_results(actual_requests, counts, total_time_seconds,
                                          timeout_seconds=self.args.request_timeout,
                                          idle_timeout_seconds=self.args.idle_timeout, show_counts=not only_stage)
        server_died: bool = stage_run.get("server_died")
        interrupted: bool = stage_run.get("interrupted")
        should_abort: bool = server_died or interrupted
        if not should_abort:
            should_abort = OutputValidator.check_permission_failures(results, self.args.agent)
        if not should_abort:
            should_abort = OutputValidator.check_timeout_abort(counts)
        stage_check: Dict[str, Any] = {
            "counts": counts,
            "retries": stage_retries.get("retries"),
            "total_retries": stage_retries.get("total_retries"),
            "amplification": stage_retries.get("amplification"),
            "should_abort": should_abort,
        }
        return stage_check

    def _count_stage_retries(self, stage_inputs: Dict[str, Any], stage_start: Dict[str, Any]) -> Dict[str, Any]:
        """
        Count the server retries of a stage from the server log.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :param stage_start: The dict from _start_stage()
        :return: Dict with "retries" (retry count per error type, empty without a server log), "total_retries" and
            "amplification" (server calls per request, 1.0 without a server log)
        """
        retries: Dict[str, int] = {}
        total_retries: int = 0
        amplification: float = 1.0
        if stage_inputs.get("has_server_log"):
            log_position: Optional[int] = stage_start.get("log_position")
            retries = self.log_monitor.count_retries_since(log_position)
            retry_count: int
            # Add up the retries of every error type.
            for retry_count in retries.values():
                total_retries += retry_count
            stage_requests: int = stage_start.get("stage_requests")
            amplification = Formatters.compute_amplification(stage_requests, total_retries)
        stage_retries: Dict[str, Any] = {
            "retries": retries,
            "total_retries": total_retries,
            "amplification": amplification,
        }
        return stage_retries

    def _collect_after_stage(self, stage_inputs: Dict[str, Any], stage_start: Dict[str, Any],
                             stage_run: Dict[str, Any], stage_check: Dict[str, Any]) -> Dict[str, Any]:
        """
        Log the retry activity of a stage, then settle, snapshot and analyze the server log.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :param stage_start: The dict from _start_stage()
        :param stage_run: The dict from _fire_stage()
        :param stage_check: The dict from _check_stage()
        :return: The dict from StageDataCollector.collect_post_stage_data()
        """
        has_server_log: bool = stage_inputs.get("has_server_log")
        stage_requests: int = stage_start.get("stage_requests")
        if has_server_log and stage_requests > 0:
            retries: Dict[str, int] = stage_check.get("retries")
            total_retries: int = stage_check.get("total_retries")
            OutputValidator.log_retry_activity(retries, total_retries, stage_requests)
        post_stage_inputs: Dict[str, Any] = {
            "actual_requests": stage_inputs.get("actual_requests"),
            "monitor_resources": stage_inputs.get("monitor_resources"),
            "has_server_log": has_server_log,
            "log_position": stage_start.get("log_position"),
            "results": stage_run.get("results"),
            "before_server": stage_start.get("before_server"),
            "before_client": stage_start.get("before_client"),
            "peak_client": stage_run.get("peak_client"),
            "settled_client": stage_run.get("settled_client"),
            "server_log_requests": stage_requests,
        }
        post_stage_data: Dict[str, Any] = self._data_collector.collect_post_stage_data(post_stage_inputs)
        return post_stage_data

    @staticmethod
    def _server_log_values(post_stage_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Read the server log values of a stage for its summary. An aborted stage skips the server log analysis,
        so its post_stage_data is empty and its server log values are empty too.

        :param post_stage_data: The dict from _collect_after_stage(), or an empty dict for an aborted stage
        :return: Dict with "server_counts", "disconnections", "server_errors", "tool_warnings", "network_tokens",
            "validation_events" and "after_server" (server snapshot after the stage, or None)
        """
        server_counts: Dict[str, Any] = post_stage_data.get("server_counts", {})
        disconnections: List[Dict[str, str]] = post_stage_data.get("disconnections", [])
        server_errors: List[Dict[str, str]] = post_stage_data.get("server_errors", [])
        tool_warnings: List[Dict[str, str]] = post_stage_data.get("tool_warnings", [])
        network_tokens: List[Dict[str, Any]] = post_stage_data.get("network_tokens", [])
        validation_events: List[Dict[str, Any]] = post_stage_data.get("validation_events", [])
        after_server: Optional[Dict[str, Any]] = post_stage_data.get("after_server")
        server_log_values: Dict[str, Any] = {
            "server_counts": server_counts,
            "disconnections": disconnections,
            "server_errors": server_errors,
            "tool_warnings": tool_warnings,
            "network_tokens": network_tokens,
            "validation_events": validation_events,
            "after_server": after_server,
        }
        return server_log_values

    def _capture_before_snapshots(self, client_process: Process) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Capture and log the server, client and system resources before a stage.

        :param client_process: The client process
        :return: Dict with "server" (server snapshot, or None when not available) and "client" (client snapshot,
            or None)
        """
        before_server: Optional[Dict[str, Any]] = self._data_collector.snapshot_server_process()
        if before_server:
            ResourceMonitor.log_snapshot("Server BEFORE", before_server)
        elif not self.args.client_only:
            self.logger.info("  Server BEFORE: not available (server not running)")

        before_client: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(client_process)
        if before_client:
            client_rss_megabytes: float = before_client.get("rss_megabytes")
            client_cpu_percent: float = before_client.get("cpu_percent")
            self.logger.info("  Client BEFORE: RSS %.1f MB, CPU %.1f%%", client_rss_megabytes, client_cpu_percent)

        ResourceMonitor.log_system_memory("BEFORE")
        before_snapshots: Dict[str, Optional[Dict[str, Any]]] = {
            "server": before_server,
            "client": before_client,
        }
        return before_snapshots

    def _log_fire_info(self, actual_requests: int, monitor_resources: bool,
                       probe_result: Optional[Dict[str, Any]]) -> None:
        """
        Log the 'Firing N requests' line with thread count.

        :param actual_requests: Number of requests this stage fires
        :param monitor_resources: When True and a local server process is known, the line also shows the
                                  server thread count
        :param probe_result: Result of the dry-run probe to count in this stage, or None
        """
        fire_seconds: float = time()
        fire_local_time: struct_time = localtime(fire_seconds)
        fire_timestamp: str = strftime("%H:%M:%S", fire_local_time)
        fire_threads: str = ""
        if monitor_resources and self.server_process:
            try:
                fire_threads = f"  threads: {self.server_process.num_threads()}"
            except (NoSuchProcess, AccessDenied) as exc:
                self.logger.debug("Thread count unavailable: %s", exc)
        fire_label: str = str(actual_requests)
        if probe_result is not None:
            fire_label = f"{actual_requests} ({actual_requests - 1} + 1 probe)"
        self.logger.info("\nFiring %s %s requests... [%s]%s", fire_label, self.args.agent, fire_timestamp, fire_threads)
