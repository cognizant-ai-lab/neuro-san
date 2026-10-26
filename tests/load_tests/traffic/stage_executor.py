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
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.stage_data_collector import StageDataCollector
from tests.load_tests.reporting.stage_summary_builder import StageSummaryBuilder
from tests.load_tests.reporting.system_resources import SystemResources
from tests.load_tests.traffic.runner import TrafficRunner
from tests.load_tests.traffic.stage_plan import StagePlan
from tests.load_tests.validation.output_validator import OutputValidator


class StageExecutor:  # pylint: disable=too-many-instance-attributes
    """
    Runs the stages of one load test, round by round, and builds the summary dict of each stage.
    Stops early at the --max-requests cap, at --total-timeout, or when a stage must abort the test.
    """

    LOGGER: Logger = getLogger(__name__)

    # 60 "#" characters: the line around the round header.
    ROUND_HEADER_LINE: str = "############################################################"

    def __init__(self, args: Namespace, runner: TrafficRunner, executor_parts: Dict[str, Any]) -> None:
        """
        Keep the run's arguments, the traffic runner and the parts each stage needs.

        :param args: Parsed command-line arguments
        :param runner: Traffic runner that sends the requests of a stage
        :param executor_parts: A dict with "profile" (the AgentProfile), "log_monitor" (the ServerLogMonitor, or
            None), "resource_reporter" (the ResourceReporter), "server_process" (the local server process, or None),
            "output_dir" (the run's output directory), "probe_result" (result of the dry-run probe, or None) and
            "server_log" (server log path, or None)
        """
        self.args: Namespace = args
        self.runner: TrafficRunner = runner
        self.profile: AgentProfile = executor_parts.get("profile")
        self.log_monitor: Optional[ServerLogMonitor] = executor_parts.get("log_monitor")
        self.server_process: Optional[Process] = executor_parts.get("server_process")
        self.probe_result: Optional[Dict[str, Any]] = executor_parts.get("probe_result")
        self.server_log: Optional[str] = executor_parts.get("server_log")
        self._output_dir: Optional[str] = executor_parts.get("output_dir")
        collector_parts: Dict[str, Any] = {
            "profile": self.profile,
            "log_monitor": self.log_monitor,
            "resource_reporter": executor_parts.get("resource_reporter"),
            "server_process": self.server_process,
            "output_dir": self._output_dir,
        }
        self._data_collector: StageDataCollector = StageDataCollector(args, collector_parts)
        self._aborted: bool = False
        self._interrupted: bool = False

    def run_all_stages(  # pylint: disable=too-many-locals
            self, stages: List[int], total_cap: int) -> List[Dict[str, Any]]:
        """
        Execute all stages of the load test, collecting data per stage.

        :param stages: Request count of each stage, in order
        :param total_cap: Most requests to send in the whole test
        :return: One summary dict per stage that runs
        """
        monitor_resources: bool = (self.args.level != LoadTestConstants.LEVEL_MIN
                                   or self.args.client_only
                                   or self.args.server_only)
        has_server_log: bool = self.server_log is not None
        probe_result: Optional[Dict[str, Any]] = self.probe_result
        only_stage: bool = len(stages) == 1 and self.args.num_rounds == 1

        stage_summaries: List[Dict[str, Any]] = []
        global_offset: int = 0
        total_sent: int = 0
        test_start_seconds: float = perf_counter()

        round_num: int
        # Run every stage once per round.
        for round_num in range(1, self.args.num_rounds + 1):
            if self.args.num_rounds > 1:
                StageExecutor.LOGGER.info("\n%s", StageExecutor.ROUND_HEADER_LINE)
                StageExecutor.LOGGER.info("  ROUND %s of %s", round_num, self.args.num_rounds)
                StageExecutor.LOGGER.info("%s", StageExecutor.ROUND_HEADER_LINE)

            stage_index: int
            num_concurrent: int
            # Run each stage, stopping at the request cap or the total timeout.
            for stage_index, num_concurrent in enumerate(stages):
                if total_sent >= total_cap:
                    total_planned: int = sum(stages) * self.args.num_rounds
                    StageExecutor.LOGGER.warning(
                        """
WARNING: Reached --max-requests cap (%s). Only %s of %s total planned requests completed.
         Use --max-requests %s to run all planned requests.""",
                        total_cap, total_sent, total_planned, total_planned,
                    )
                    return stage_summaries

                if self._total_timeout_reached(test_start_seconds):
                    self._aborted = True
                    return stage_summaries

                remaining: int = total_cap - total_sent
                actual_requests: int = min(num_concurrent, remaining)

                stage_inputs: Dict[str, Any] = {
                    "actual_requests": actual_requests,
                    "num_concurrent": num_concurrent,
                    "stage_num": stage_index + 1,
                    "round_num": round_num,
                    "global_offset": global_offset,
                    "monitor_resources": monitor_resources,
                    "has_server_log": has_server_log,
                    "probe_result": probe_result,
                    "only_stage": only_stage,
                }
                stage_result: Dict[str, Any] = self._run_single_stage(stage_inputs)
                summary: Dict[str, Any] = stage_result.get("summary")
                probe_used: bool = stage_result.get("probe_used")
                should_abort: bool = stage_result.get("should_abort")

                global_offset += actual_requests
                total_sent += actual_requests
                if probe_used:
                    probe_result = None
                stage_summaries.append(summary)
                if should_abort:
                    self._aborted = True
                    return stage_summaries

        return stage_summaries

    def was_aborted(self) -> bool:
        """
        Return True when a stage or --total-timeout stopped the test.

        :return: True when the test stops early on an abort
        """
        return self._aborted

    def was_interrupted(self) -> bool:
        """
        Return True when the traffic runner reports a Ctrl-C during a stage.

        :return: True when a stage is interrupted
        """
        return self._interrupted

    def _total_timeout_reached(self, test_start_seconds: float) -> bool:
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
        StageExecutor.LOGGER.warning(
            """
  ABORT: --total-timeout (%ss) reached after %.0fs.
  Stopping test and reporting available results.""",
            limit_seconds, elapsed_seconds,
        )
        return True

    def _run_single_stage(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
            self, stage_inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute one stage of the load test.

        :param stage_inputs: A dictionary with "actual_requests" (number of requests to send in this stage),
            "num_concurrent" (requested concurrency before the --max-requests cap), "stage_num" and "round_num"
            (starting at 1), "global_offset" (number of requests sent by earlier stages), "monitor_resources" (True to
            take resource snapshots around the stage), "has_server_log" (True when the server log can be read),
            "probe_result" (result of the dry-run probe to count in this stage, or None) and "only_stage" (True when
            this is the only stage)
        :return: Dict with "summary" (the stage summary dict), "probe_used" (True when probe_result was counted)
            and "should_abort" (True when the test must stop after this stage)
        """
        actual_requests: int = stage_inputs.get("actual_requests")
        num_concurrent: int = stage_inputs.get("num_concurrent")
        stage_num: int = stage_inputs.get("stage_num")
        round_num: int = stage_inputs.get("round_num")
        global_offset: int = stage_inputs.get("global_offset")
        monitor_resources: bool = stage_inputs.get("monitor_resources")
        has_server_log: bool = stage_inputs.get("has_server_log")
        probe_result: Optional[Dict[str, Any]] = stage_inputs.get("probe_result")
        only_stage: bool = stage_inputs.get("only_stage", False)

        stage_workers: int = self.args.max_workers
        if self.args.ramp:
            stage_workers = actual_requests

        StageExecutor.LOGGER.info("\n%s", Formatters.SEPARATOR_LINE)
        stage_label: str = ""
        if self.args.ramp:
            stage_label = f"[STAGE {stage_num}] {actual_requests} requests (max {stage_workers} workers)"
            if self.args.num_rounds > 1:
                stage_label += f" (round {round_num})"
        else:
            stage_label = f"{actual_requests} requests (max {stage_workers} workers)"
            if self.args.num_rounds > 1:
                stage_label += f" (round {round_num})"
        StageExecutor.LOGGER.info("  %s", stage_label)
        StageExecutor.LOGGER.info("%s", Formatters.SEPARATOR_LINE)

        if actual_requests < num_concurrent:
            StageExecutor.LOGGER.info("  (Capped from %s to %s by --max-requests)", num_concurrent, actual_requests)

        log_position: Optional[int] = None
        if has_server_log:
            log_position = self.log_monitor.read_position()

        client_process: Optional[Process] = None
        before_server: Optional[Dict[str, Any]] = None
        before_client: Optional[Dict[str, Any]] = None
        if monitor_resources:
            client_process = Process()
            before_snapshots: Dict[str, Optional[Dict[str, Any]]] = self._capture_before_snapshots(client_process)
            before_server = before_snapshots.get("server")
            before_client = before_snapshots.get("client")

        self._log_fire_info(actual_requests, monitor_resources, probe_result)

        # If a dry-run probe ran, inject it into stage 1.  The probe
        # fired before log_position was captured, so only stage_requests of
        # them appear in the server log from here on.
        stage_requests: int = actual_requests
        probe_used: bool = probe_result is not None
        if probe_used:
            stage_requests = max(actual_requests - 1, 0)

        stop_event: Event = Event()
        monitor: Optional[Thread] = None
        if has_server_log:
            monitor_start_seconds: float = perf_counter()
            primary_start_pattern: str = self.profile.get_primary_start_pattern()
            monitor = self.log_monitor.start_log_monitor(
                log_position, stage_requests, monitor_start_seconds, stop_event, client_process=client_process,
                primary_start_pattern=primary_start_pattern, output_dir=self._output_dir)

        system_before: Dict[str, Optional[float]] = SystemResources.snapshot()
        before_system_memory_percent: Optional[float] = system_before.get("mem_pct")

        first_request_number: int = global_offset
        # The dry-run probe is the first request of the stage.
        if probe_used:
            first_request_number += 1
        plan: StagePlan = StagePlan(stage_requests, stage_workers, first_request_number, self._output_dir)
        stage_run: Dict[str, Any] = self.runner.run_stage(plan, server_process=self.server_process,
                                                          client_process=client_process, log_monitor=self.log_monitor)
        elapsed_seconds: float = stage_run.get("total_time_seconds")
        results: List[Dict[str, Any]] = stage_run.get("results")
        peak_threads: Optional[int] = stage_run.get("peak_server_threads")
        peak_client_rss_megabytes: Optional[float] = stage_run.get("peak_client_rss_megabytes")
        peak_server_rss_megabytes: Optional[float] = stage_run.get("peak_server_rss_megabytes")
        peak_system_memory: Optional[Dict[str, float]] = stage_run.get("peak_system_memory")
        peak_system_cpu_percent: Optional[float] = stage_run.get("peak_system_cpu_percent")
        peak_system_threads: Optional[int] = stage_run.get("peak_system_threads")
        server_died: bool = stage_run.get("server_died")
        interrupted: bool = stage_run.get("interrupted")
        if interrupted:
            self._interrupted = True

        if probe_used:
            results.insert(0, probe_result)
            elapsed_seconds += probe_result.get("elapsed", 0.0)

        stop_event.set()
        if monitor:
            monitor.join(timeout=LoadTestConstants.THREAD_JOIN_TIMEOUT_SECONDS)

        peak_client: Optional[Dict[str, Any]] = None
        settled_client: Optional[Dict[str, Any]] = None
        if monitor_resources:
            if peak_client_rss_megabytes is not None:
                peak_client = {"rss_megabytes": peak_client_rss_megabytes}
            settled_client = ResourceMonitor.snapshot(client_process)

        counts: Dict[str, Any] = OutputValidator.count_results(results)

        retries: Dict[str, int] = {}
        total_retries: int = 0
        amplification: float = 1.0
        if has_server_log:
            retries = self.log_monitor.count_retries_since(log_position)
            retry_count: int
            # Add up the retries of every error type.
            for retry_count in retries.values():
                total_retries += retry_count
            amplification = Formatters.compute_amplification(stage_requests, total_retries)

        OutputValidator.log_stage_results(actual_requests, counts, elapsed_seconds,
                                          timeout_seconds=self.args.request_timeout,
                                          idle_timeout_seconds=self.args.idle_timeout, show_counts=not only_stage)
        should_abort: bool = server_died or interrupted
        if not should_abort:
            should_abort = OutputValidator.check_permission_failures(results, self.args.agent)
        if not should_abort:
            should_abort = OutputValidator.check_timeout_abort(counts)
        post_stage_data: Dict[str, Any] = {}
        if not should_abort:
            if has_server_log and stage_requests > 0:
                OutputValidator.log_retry_activity(retries, total_retries, stage_requests)
            post_stage_inputs: Dict[str, Any] = {
                "actual_requests": actual_requests,
                "monitor_resources": monitor_resources,
                "has_server_log": has_server_log,
                "log_position": log_position,
                "results": results,
                "before_server": before_server,
                "before_client": before_client,
                "peak_client": peak_client,
                "settled_client": settled_client,
                "server_log_requests": stage_requests,
            }
            post_stage_data = self._data_collector.collect_post_stage_data(post_stage_inputs)
        system_after: Dict[str, Optional[float]] = SystemResources.snapshot()
        after_system_memory_percent: Optional[float] = system_after.get("mem_pct")
        # An aborted stage skips the server log analysis, so its server log values are empty.
        server_counts: Dict[str, Any] = post_stage_data.get("server_counts", {})
        disconnections: List[Dict[str, str]] = post_stage_data.get("disconnections", [])
        server_errors: List[Dict[str, str]] = post_stage_data.get("server_errors", [])
        tool_warnings: List[Dict[str, str]] = post_stage_data.get("tool_warnings", [])
        network_tokens: List[Dict[str, Any]] = post_stage_data.get("network_tokens", [])
        validation_events: List[Dict[str, Any]] = post_stage_data.get("validation_events", [])
        after_server: Optional[Dict[str, Any]] = post_stage_data.get("after_server")
        stage_values: Dict[str, Any] = {
            "stage_num": stage_num,
            "round_num": round_num,
            "actual_requests": actual_requests,
            "counts": counts,
            "elapsed": elapsed_seconds,
            "retries": retries,
            "total_retries": total_retries,
            "amplification": amplification,
            "results": results,
            "server_counts": server_counts,
            "disconnections": disconnections,
            "server_errors": server_errors,
            "tool_warnings": tool_warnings,
            "network_tokens": network_tokens,
            "validation_events": validation_events,
            "has_server_log": has_server_log,
            "has_tokens": self.args.include_tokens,
            "monitor_resources": monitor_resources,
            "before_server": before_server,
            "after_server": after_server,
            "peak_threads": peak_threads,
            "peak_server_rss": peak_server_rss_megabytes,
            "before_client": before_client,
            "peak_client": peak_client,
            "settled_client": settled_client,
            "before_system_memory_percent": before_system_memory_percent,
            "after_system_memory_percent": after_system_memory_percent,
            "peak_system_memory": peak_system_memory,
            "peak_system_cpu_percent": peak_system_cpu_percent,
            "before_sys": system_before,
            "after_sys": system_after,
            "peak_system_threads": peak_system_threads,
        }
        summary_entry: Dict[str, Any] = StageSummaryBuilder.build_stage_summary(stage_values)
        stage_result: Dict[str, Any] = {
            "summary": summary_entry,
            "probe_used": probe_used,
            "should_abort": should_abort,
        }
        return stage_result

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
            StageExecutor.LOGGER.info("  Server BEFORE: not available (server not running)")

        before_client: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(client_process)
        if before_client:
            client_rss_megabytes: float = before_client.get("rss_megabytes")
            client_cpu_percent: float = before_client.get("cpu_percent")
            StageExecutor.LOGGER.info("  Client BEFORE: RSS %.1f MB, CPU %.1f%%",
                                      client_rss_megabytes, client_cpu_percent)

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
                StageExecutor.LOGGER.debug("Thread count unavailable: %s", exc)
        fire_label: str = str(actual_requests)
        if probe_result is not None:
            fire_label = f"{actual_requests} ({actual_requests - 1} + 1 probe)"
        StageExecutor.LOGGER.info("\nFiring %s %s requests... [%s]%s",
                                  fire_label, self.args.agent, fire_timestamp, fire_threads)
