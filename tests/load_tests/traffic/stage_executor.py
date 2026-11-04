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

from leaf_common.logging.sensitive_logger import SensitiveLogger

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.process_read_error import ProcessReadError
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.monitoring.tracked_process import TrackedProcess
from tests.load_tests.reporting.duration_parser import DurationParser
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.stage_data_collector import StageDataCollector
from tests.load_tests.reporting.stage_summary_builder import StageSummaryBuilder
from tests.load_tests.reporting.system_resources import SystemResources
from tests.load_tests.traffic.traffic_runner import TrafficRunner
from tests.load_tests.traffic.stage_plan import StagePlan
from tests.load_tests.validation.output_validator import OutputValidator


class StageExecutor:
    """
    Runs one stage of a load test and builds its summary dict, and checks --total-timeout.
    StageRun runs the stages round by round.
    """

    def __init__(self, runner: TrafficRunner, executor_parts: Dict[str, Any]) -> None:
        """
        Keep the run's arguments, the traffic runner and the parts each stage needs.

        :param runner: Traffic runner that sends the requests of a stage
        :param executor_parts: A dict with the following keys:
            "profile"                  The AgentProfile
            "log_monitor"              The ServerLogMonitor, or None
            "resource_reporter"        The ResourceReporter
            "server_process"           The local server process, or None
            "output_dir"               The run's output directory
            "agent"                    Agent name
            "level"                    Test level, for the StageDataCollector
            "client_only"              True with --client-only
            "settle_time_seconds"      --settle-time in seconds, for the StageDataCollector
            "include_tokens"           True to put token counts in the stage results
            "max_workers"              --max-workers: most concurrent requests
            "ramp"                     True with --ramp
            "num_rounds"               --num-rounds: rounds of each stage
            "request_timeout_seconds"  --request-timeout in seconds
            "idle_timeout_seconds"     --idle-timeout in seconds
            "total_timeout_seconds"    --total-timeout in seconds, 0 for none
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.resource_monitor: ResourceMonitor = ResourceMonitor()
        self.output_validator: OutputValidator = OutputValidator()
        # A dict, not one member per value: the constructor docstring lists the keys this class reads.
        self._settings: Dict[str, Any] = executor_parts
        self.runner: TrafficRunner = runner
        # executor_parts already holds every key that StageDataCollector reads.
        self._data_collector: StageDataCollector = StageDataCollector(executor_parts)

    def total_timeout_reached(self, test_start_seconds: float) -> bool:
        """
        Check if total-timeout has been exceeded.

        Logs a warning when the elapsed time since
        test_start_seconds reaches --total-timeout (0 means disabled).

        :param test_start_seconds: perf_counter() at the start of the test
        :return: True when the total timeout is reached
        """
        limit_seconds: float = self._settings.get("total_timeout_seconds")
        if limit_seconds <= 0:
            return False
        elapsed_seconds: float = perf_counter() - test_start_seconds
        if elapsed_seconds < limit_seconds:
            return False
        elapsed_text: str = DurationParser.format_minutes_seconds(elapsed_seconds)
        self.logger.warning("""
  ABORT: --total-timeout (%ss) reached after %s.
  Stopping test and reporting available results.""", limit_seconds, elapsed_text)
        return True

    def run_single_stage(self, stage_inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute one stage of the load test.

        :param stage_inputs: A dict with the following keys:
            "actual_requests"        Number of requests to send in this stage
            "num_concurrent"         Requested concurrency before the --max-requests cap
            "stage_num"              Stage number, starting at 1
            "round_num"              Round number, starting at 1
            "global_offset"          Number of requests sent by earlier stages
            "monitor_resources"      True to take resource snapshots around the stage
            "has_server_log"         True when the server log can be read
            "probe_result"           Result of the dry-run probe to count in this stage, or None
            "only_stage"             True when this is the only stage
            "primary_start_pattern"  Server log pattern of a primary request start
        :return: A dict with the following keys:
            "summary"       The stage summary dict
            "probe_used"    True when probe_result was counted
            "should_abort"  True when the test must stop after this stage
            "interrupted"   True when Ctrl-C stops the stage
        """
        include_tokens: bool = self._settings.get("include_tokens")
        stage_start: Dict[str, Any] = self._start_stage(stage_inputs)
        stage_run: Dict[str, Any] = self._fire_stage(stage_inputs, stage_start)
        stage_check: Dict[str, Any] = self._check_stage(stage_inputs, stage_start, stage_run)
        post_stage_data: Dict[str, Any] = {}
        if not stage_check.get("should_abort"):
            post_stage_data = self._collect_after_stage(stage_inputs, stage_start, stage_run, stage_check)
        after_system: Dict[str, Optional[float]] = SystemResources.snapshot()
        stage_values: Dict[str, Any] = {
            "has_tokens": include_tokens,
            "after_system": after_system,
        }
        # Each helper's dict already uses the key names that build_stage_summary() reads.
        stage_values.update(stage_inputs)
        stage_values.update(stage_start)
        stage_values.update(stage_run)
        stage_values.update(stage_check)
        stage_values.update(post_stage_data)
        summary_builder: StageSummaryBuilder = StageSummaryBuilder(stage_values)
        summary_entry: Dict[str, Any] = summary_builder.build_stage_summary()
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
        max_workers: int = self._settings.get("max_workers")
        ramp: bool = self._settings.get("ramp")
        stage_workers: int = max_workers
        if ramp:
            stage_workers = stage_inputs.get("actual_requests")
        return stage_workers

    def _log_stage_header(self, stage_inputs: Dict[str, Any], stage_workers: int) -> None:
        """
        Log the header of a stage: its request count, worker count and round.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :param stage_workers: Most worker threads the stage uses
        """
        ramp: bool = self._settings.get("ramp")
        num_rounds: int = self._settings.get("num_rounds")
        actual_requests: int = stage_inputs.get("actual_requests")
        num_concurrent: int = stage_inputs.get("num_concurrent")
        stage_num: int = stage_inputs.get("stage_num")
        round_num: int = stage_inputs.get("round_num")
        stage_label: str = f"{actual_requests} requests (max {stage_workers} workers)"
        if ramp:
            stage_label = f"[STAGE {stage_num}] {stage_label}"
        if num_rounds > 1:
            stage_label += f" (round {round_num})"
        self.logger.info("\n%s", Formatters.section_header(stage_label))

        if actual_requests < num_concurrent:
            self.logger.info("  (Capped from %s to %s by --max-requests)", num_concurrent, actual_requests)

    def _start_stage(self, stage_inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Log the stage header and take the server log position and the resource snapshots before the stage.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :return: A dict with the following keys:
            "stage_workers"   Most worker threads
            "log_position"    Server log offset, or None
            "client_process"  The client process, or None without resource monitoring
            "before_server"   Server snapshot, or None
            "before_client"   Client snapshot, or None
            "stage_requests"  Number of requests to fire, without the probe
            "probe_used"      True when the dry-run probe counts as the first request
        """
        log_monitor: Optional[ServerLogMonitor] = self._settings.get("log_monitor")
        actual_requests: int = stage_inputs.get("actual_requests")
        monitor_resources: bool = stage_inputs.get("monitor_resources")
        probe_result: Optional[Dict[str, Any]] = stage_inputs.get("probe_result")
        stage_workers: int = self._stage_workers(stage_inputs)
        self._log_stage_header(stage_inputs, stage_workers)

        log_position: Optional[int] = None
        if stage_inputs.get("has_server_log"):
            log_position = log_monitor.read_position()

        client_process: Optional[TrackedProcess] = None
        before_snapshots: Dict[str, Optional[Dict[str, Any]]] = {}
        if monitor_resources:
            client_process = TrackedProcess()
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
            "total_time_seconds", plus the following keys:
            "before_system"   System snapshot before the requests
            "peak_client"     Peak client RSS snapshot, or None
            "settled_client"  Client snapshot after the stage, or None
        """
        probe_result: Optional[Dict[str, Any]] = stage_inputs.get("probe_result")
        probe_used: bool = stage_start.get("probe_used")
        client_process: Optional[TrackedProcess] = stage_start.get("client_process")
        stop_event: Event = Event()
        monitor: Optional[Thread] = None
        if stage_inputs.get("has_server_log"):
            monitor = self._start_log_monitor(stage_inputs, stage_start, stop_event)

        before_system: Dict[str, Optional[float]] = SystemResources.snapshot()

        stage_run: Dict[str, Any] = self._run_stage_plan(stage_inputs, stage_start)
        if probe_used:
            StageExecutor._count_probe(stage_run, probe_result)

        stop_event.set()
        if monitor:
            monitor.join(timeout=LoadTestConstants.THREAD_JOIN_TIMEOUT_SECONDS)

        stage_run["before_system"] = before_system
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
        log_monitor: Optional[ServerLogMonitor] = self._settings.get("log_monitor")
        output_dir: Optional[str] = self._settings.get("output_dir")
        monitor_start_seconds: float = perf_counter()
        primary_start_pattern: str = stage_inputs.get("primary_start_pattern")
        log_position: Optional[int] = stage_start.get("log_position")
        stage_requests: int = stage_start.get("stage_requests")
        client_process: Optional[TrackedProcess] = stage_start.get("client_process")
        monitor_settings: Dict[str, Any] = {
            "position": log_position,
            "expected_count": stage_requests,
            "fire_time_seconds": monitor_start_seconds,
            "stop_event": stop_event,
            "client_process": client_process,
            "primary_start_pattern": primary_start_pattern,
            "output_dir": output_dir,
        }
        monitor: Optional[Thread] = log_monitor.start_log_monitor(monitor_settings)
        return monitor

    def _run_stage_plan(self, stage_inputs: Dict[str, Any], stage_start: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fire the requests of a stage through TrafficRunner.run_stage().

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :param stage_start: The dict from _start_stage()
        :return: The stage run dict of TrafficRunner.run_stage()
        """
        log_monitor: Optional[ServerLogMonitor] = self._settings.get("log_monitor")
        server_process: Optional[TrackedProcess] = self._settings.get("server_process")
        output_dir: Optional[str] = self._settings.get("output_dir")
        probe_used: bool = stage_start.get("probe_used")
        client_process: Optional[TrackedProcess] = stage_start.get("client_process")
        first_request_number: int = stage_inputs.get("global_offset")
        # The dry-run probe is the first request of the stage.
        if probe_used:
            first_request_number += 1
        stage_requests: int = stage_start.get("stage_requests")
        stage_workers: int = stage_start.get("stage_workers")
        plan: StagePlan = StagePlan(stage_requests, stage_workers, first_request_number, output_dir)
        stage_run: Dict[str, Any] = self.runner.run_stage(plan, server_process=server_process,
                                                          client_process=client_process, log_monitor=log_monitor)
        return stage_run

    def _check_stage(self, stage_inputs: Dict[str, Any], stage_start: Dict[str, Any],
                     stage_run: Dict[str, Any]) -> Dict[str, Any]:
        """
        Count the results and the server retries of a stage, log them, and decide if the test must stop.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :param stage_start: The dict from _start_stage()
        :param stage_run: The dict from _fire_stage()
        :return: A dict with the following keys:
            "counts"         Result counts
            "retries"        Retry count per error type
            "total_retries"  Number of retries of all types
            "amplification"  Server calls per request
            "should_abort"   True when the test must stop
        """
        agent: str = self._settings.get("agent")
        results: List[Dict[str, Any]] = stage_run.get("results")
        counts: Dict[str, Any] = OutputValidator.count_results(results)
        stage_retries: Dict[str, Any] = self._count_stage_retries(stage_inputs, stage_start)

        self._log_stage_results(stage_inputs, stage_run, counts)
        server_died: bool = stage_run.get("server_died")
        interrupted: bool = stage_run.get("interrupted")
        should_abort: bool = server_died or interrupted
        if not should_abort:
            should_abort = self.output_validator.check_permission_failures(results, agent)
        if not should_abort:
            should_abort = self.output_validator.check_timeout_abort(counts)
        stage_check: Dict[str, Any] = {
            "counts": counts,
            "retries": stage_retries.get("retries"),
            "total_retries": stage_retries.get("total_retries"),
            "amplification": stage_retries.get("amplification"),
            "should_abort": should_abort,
        }
        return stage_check

    def _log_stage_results(self, stage_inputs: Dict[str, Any], stage_run: Dict[str, Any],
                           counts: Dict[str, Any]) -> None:
        """
        Log the result counts and the time of a stage.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :param stage_run: The dict from _fire_stage()
        :param counts: Result counts from OutputValidator.count_results()
        """
        request_timeout_seconds: float = self._settings.get("request_timeout_seconds")
        idle_timeout_seconds: float = self._settings.get("idle_timeout_seconds")
        actual_requests: int = stage_inputs.get("actual_requests")
        total_time_seconds: float = stage_run.get("total_time_seconds")
        only_stage: bool = stage_inputs.get("only_stage", False)
        self.output_validator.log_stage_results(actual_requests, counts, total_time_seconds,
                                                timeout_seconds=request_timeout_seconds,
                                                idle_timeout_seconds=idle_timeout_seconds, show_counts=not only_stage)

    def _count_stage_retries(self, stage_inputs: Dict[str, Any], stage_start: Dict[str, Any]) -> Dict[str, Any]:
        """
        Count the server retries of a stage from the server log.

        :param stage_inputs: The stage_inputs dict of run_single_stage()
        :param stage_start: The dict from _start_stage()
        :return: A dict with the following keys:
            "retries"        Retry count per error type, empty without a server log
            "total_retries"  Number of retries of all types
            "amplification"  Server calls per request, 1.0 without a server log
        """
        log_monitor: Optional[ServerLogMonitor] = self._settings.get("log_monitor")
        retries: Dict[str, int] = {}
        total_retries: int = 0
        amplification: float = 1.0
        if stage_inputs.get("has_server_log"):
            log_position: Optional[int] = stage_start.get("log_position")
            retries = log_monitor.count_retries_since(log_position)
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
            self.output_validator.log_retry_activity(retries, total_retries, stage_requests)
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

    def _capture_before_snapshots(self, client_process: TrackedProcess) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Capture and log the server, client and system resources before a stage.

        :param client_process: The client process
        :return: A dict with the following keys:
            "server"  Server snapshot, or None when not available
            "client"  Client snapshot, or None
        """
        client_only: bool = self._settings.get("client_only")
        before_server: Optional[Dict[str, Any]] = self._data_collector.snapshot_server_process()
        if before_server:
            self.resource_monitor.log_snapshot("Server BEFORE", before_server)
        elif not client_only:
            self.logger.info("  Server BEFORE: not available (server not running)")

        before_client: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(client_process)
        if before_client:
            client_rss_megabytes: float = before_client.get("rss_megabytes")
            client_cpu_percent: float = before_client.get("cpu_percent")
            self.logger.info("  Client BEFORE: RSS %.1f MB, CPU %.1f%%", client_rss_megabytes, client_cpu_percent)

        self.resource_monitor.log_system_memory("BEFORE")
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
        server_process: Optional[TrackedProcess] = self._settings.get("server_process")
        agent: str = self._settings.get("agent")
        fire_seconds: float = time()
        fire_local_time: struct_time = localtime(fire_seconds)
        fire_timestamp: str = strftime("%H:%M:%S", fire_local_time)
        fire_threads: str = ""
        if monitor_resources and server_process:
            try:
                fire_threads = f"  threads: {server_process.num_threads()}"
            except ProcessReadError as exc:
                sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)
                sensitive_logger.debug("Thread count unavailable: %s", exc)
        fire_label: str = str(actual_requests)
        if probe_result is not None:
            fire_label = f"{actual_requests} ({actual_requests - 1} + 1 probe)"
        self.logger.info("\nFiring %s %s requests... [%s]%s", fire_label, agent, fire_timestamp, fire_threads)
