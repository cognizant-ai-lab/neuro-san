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

# pylint: disable=too-many-lines

import argparse
import getpass
import json
import logging
import os
import platform
import re
import signal
import socket
import sys
import tempfile
import threading
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set

import psutil

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.confirm import Confirm
from tests.load_tests.load_test_arguments import LoadTestArguments
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.monitoring.server_only_monitor import ServerOnlyMonitor
from tests.load_tests.prompts.agent_profile_factory import AgentProfileFactory
from tests.load_tests.reporting.cross_run_comparison import CrossRunComparison
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.history_recorder import HistoryRecorder
from tests.load_tests.reporting.results_rebuilder import ResultsRebuilder
from tests.load_tests.reporting.disconnection_reporter import DisconnectionReporter
from tests.load_tests.reporting.json_metadata import JsonMetadata
from tests.load_tests.reporting.latency_analyzer import LatencyAnalyzer
from tests.load_tests.reporting.pool_analyzer import PoolAnalyzer
from tests.load_tests.reporting.resource_reporter import ResourceReporter
from tests.load_tests.reporting.run_log import RunLog
from tests.load_tests.reporting.run_namer import RunNamer
from tests.load_tests.reporting.stage_summary_builder import StageSummaryBuilder
from tests.load_tests.reporting.summary import SummaryReporter
from tests.load_tests.reporting.system_resources import SystemResources
from tests.load_tests.reporting.token_log_writer import TokenLogWriter
from tests.load_tests.reporting.summary_file_writer import SummaryFileWriter
from tests.load_tests.reporting.trend_history import TrendHistory
from tests.load_tests.traffic.runner import TrafficRunner
from tests.load_tests.traffic.stage_plan import StagePlan
from tests.load_tests.validation.environment_validator import EnvironmentValidator
from tests.load_tests.validation.input_validator import InputValidator
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError
from tests.load_tests.validation.output_validator import OutputValidator
from tests.load_tests.validation.server_checker import ServerChecker

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class LoadTestCli:  # pylint: disable=too-many-instance-attributes
    """
    Runs the full load test workflow for neuro-san agent networks.

    See tests/load_tests/load_tests.md for prerequisites, test levels, and
    usage examples.
    """

    # 60 "#" characters: the line around the round header.
    ROUND_HEADER_LINE: str = "############################################################"

    def __init__(self, args) -> None:
        """
        Initialize the load test CLI with parsed arguments.

        :param args: Parsed command-line arguments
        """
        self.args = args
        self.input_validator = InputValidator(args)
        self.hocon_files: List[str] = self.input_validator.validate_fixtures_hocon_dir()
        self.profile = AgentProfileFactory().create(
            args.agent, args.profile_path, args.project_root,
            hocon_files=self.hocon_files,
        )
        self.server_process = None
        self.server_log = args.server_log
        self.log_monitor: Optional[ServerLogMonitor] = None
        if self.server_log:
            self.log_monitor = ServerLogMonitor(self.server_log)
        self._cancel_event: threading.Event = threading.Event()
        self.runner: TrafficRunner = TrafficRunner(args, self.profile, self._cancel_event)
        self.resource_reporter = ResourceReporter()
        self.probe_result = None
        self._output_dir = None
        self._run_log: RunLog = RunLog()
        self._aborted = False
        self._interrupted = False
        self.server_checker: ServerChecker = ServerChecker(args)
        output_base: str = self._output_base()
        self._history_recorder: HistoryRecorder = HistoryRecorder(args, output_base)

    def _profile_source(self) -> str:
        """
        Describe where the profile came from, for logs and raw_results.json.

        :return: "hocon (<N> files)" or "json profile"
        """
        if self.hocon_files:
            return f"hocon ({len(self.hocon_files)} files)"
        return "json profile"

    # pylint: disable=too-many-locals
    def _run_all_stages(self, stages: List[int], total_cap: int) -> List[Dict[str, Any]]:
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
        test_start_seconds: float = time.perf_counter()

        round_num: int
        # Run every stage once per round.
        for round_num in range(1, self.args.num_rounds + 1):
            if self.args.num_rounds > 1:
                logger.info("\n%s", LoadTestCli.ROUND_HEADER_LINE)
                logger.info("  ROUND %s of %s", round_num, self.args.num_rounds)
                logger.info("%s", LoadTestCli.ROUND_HEADER_LINE)

            stage_idx: int
            num_concurrent: int
            # Run each stage, stopping at the request cap or the total timeout.
            for stage_idx, num_concurrent in enumerate(stages):
                if total_sent >= total_cap:
                    total_planned: int = sum(stages) * self.args.num_rounds
                    logger.warning(
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
                    "stage_num": stage_idx + 1,
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

    def _total_timeout_reached(self, test_start: float) -> bool:
        """
        Check if total-timeout has been exceeded.

        Logs a warning when the elapsed time since
        test_start reaches --total-timeout (0 means disabled).

        :param test_start: time.perf_counter() at the start of the test
        :return: True when the total timeout is reached
        """
        limit_seconds: float = self.args.total_timeout
        if limit_seconds <= 0:
            return False
        elapsed_seconds: float = time.perf_counter() - test_start
        if elapsed_seconds < limit_seconds:
            return False
        logger.warning(
            """
  ABORT: --total-timeout (%ss) reached after %.0fs.
  Stopping test and reporting available results.""",
            limit_seconds, elapsed_seconds,
        )
        return True

    # pylint: disable=too-many-locals,too-many-statements,too-many-branches
    def _run_single_stage(self, stage_inputs: Dict[str, Any]) -> Dict[str, Any]:
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

        logger.info("\n%s", Formatters.SEPARATOR_LINE)
        stage_label: str = ""
        if self.args.ramp:
            stage_label = f"[STAGE {stage_num}] {actual_requests} requests (max {stage_workers} workers)"
            if self.args.num_rounds > 1:
                stage_label += f" (round {round_num})"
        else:
            stage_label = f"{actual_requests} requests (max {stage_workers} workers)"
            if self.args.num_rounds > 1:
                stage_label += f" (round {round_num})"
        logger.info("  %s", stage_label)
        logger.info("%s", Formatters.SEPARATOR_LINE)

        if actual_requests < num_concurrent:
            logger.info("  (Capped from %s to %s by --max-requests)", num_concurrent, actual_requests)

        log_position: Optional[int] = None
        if has_server_log:
            log_position = self.log_monitor.read_position()

        client_process: Optional[psutil.Process] = None
        before_server: Optional[Dict[str, Any]] = None
        before_client: Optional[Dict[str, Any]] = None
        if monitor_resources:
            client_process = psutil.Process()
            before_snapshots: Dict[str, Optional[Dict[str, Any]]] = self._capture_before_snapshots(client_process)
            before_server = before_snapshots.get("server")
            before_client = before_snapshots.get("client")

        self._log_fire_info(actual_requests, monitor_resources, probe_result=probe_result)

        # If a dry-run probe ran, inject it into stage 1.  The probe
        # fired before log_position was captured, so only stage_requests of
        # them appear in the server log from here on.
        stage_requests: int = actual_requests
        probe_used: bool = probe_result is not None
        if probe_used:
            stage_requests = max(actual_requests - 1, 0)

        stop_event: threading.Event = threading.Event()
        monitor: Optional[threading.Thread] = None
        if has_server_log:
            monitor_start_seconds: float = time.perf_counter()
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
        system_after: Dict[str, Optional[float]] = {}
        after_system_memory_percent: Optional[float] = None
        summary_entry: Dict[str, Any] = {}
        stage_result: Dict[str, Any] = {}
        if should_abort:
            system_after = SystemResources.snapshot()
            after_system_memory_percent = system_after.get("mem_pct")
            summary_entry = StageSummaryBuilder.build_stage_summary(
                stage_num=stage_num,
                round_num=round_num,
                actual_requests=actual_requests,
                counts=counts,
                elapsed=elapsed_seconds,
                retries=retries,
                total_retries=total_retries,
                amplification=amplification,
                results=results,
                server_counts={},
                disconnections=[],
                server_errors=[],
                tool_warnings=[],
                network_tokens=[],
                validation_events=[],
                has_server_log=has_server_log,
                has_tokens=self.args.include_tokens,
                monitor_resources=monitor_resources,
                before_server=before_server,
                after_server=None,
                peak_threads=peak_threads,
                peak_server_rss=peak_server_rss_megabytes,
                before_client=before_client,
                peak_client=peak_client,
                settled_client=settled_client,
                before_system_memory_percent=before_system_memory_percent,
                after_system_memory_percent=after_system_memory_percent,
                peak_system_memory=peak_system_memory,
                peak_system_cpu_percent=peak_system_cpu_percent,
                before_sys=system_before,
                after_sys=system_after,
                peak_system_threads=peak_system_threads,
            )
            stage_result = {
                "summary": summary_entry,
                "probe_used": probe_used,
                "should_abort": True,
            }
            return stage_result

        if has_server_log and stage_requests > 0:
            OutputValidator.log_retry_activity(retries, total_retries, stage_requests)

        post_stage_data: Dict[str, Any] = self._collect_post_stage_data(
            actual_requests, monitor_resources,
            has_server_log,
            log_position, results,
            before_server=before_server,
            before_client=before_client,
            peak_client=peak_client,
            settled_client=settled_client,
            server_log_requests=stage_requests,
        )

        system_after = SystemResources.snapshot()
        after_system_memory_percent = system_after.get("mem_pct")

        server_counts: Dict[str, Any] = post_stage_data.get("server_counts")
        disconnections: List[Dict[str, str]] = post_stage_data.get("disconnections")
        server_errors: List[Dict[str, str]] = post_stage_data.get("server_errors")
        tool_warnings: List[Dict[str, str]] = post_stage_data.get("tool_warnings")
        network_tokens: List[Dict[str, Any]] = post_stage_data.get("network_tokens")
        validation_events: List[Dict[str, Any]] = post_stage_data.get("validation_events")
        after_server: Optional[Dict[str, Any]] = post_stage_data.get("after_server")
        summary_entry = StageSummaryBuilder.build_stage_summary(
            stage_num=stage_num,
            round_num=round_num,
            actual_requests=actual_requests,
            counts=counts,
            elapsed=elapsed_seconds,
            retries=retries,
            total_retries=total_retries,
            amplification=amplification,
            results=results,
            server_counts=server_counts,
            disconnections=disconnections,
            server_errors=server_errors,
            tool_warnings=tool_warnings,
            network_tokens=network_tokens,
            validation_events=validation_events,
            has_server_log=has_server_log,
            has_tokens=self.args.include_tokens,
            monitor_resources=monitor_resources,
            before_server=before_server,
            after_server=after_server,
            peak_threads=peak_threads,
            peak_server_rss=peak_server_rss_megabytes,
            before_client=before_client,
            peak_client=peak_client,
            settled_client=settled_client,
            before_system_memory_percent=before_system_memory_percent,
            after_system_memory_percent=after_system_memory_percent,
            peak_system_memory=peak_system_memory,
            peak_system_cpu_percent=peak_system_cpu_percent,
            before_sys=system_before,
            after_sys=system_after,
            peak_system_threads=peak_system_threads,
        )
        stage_result = {
            "summary": summary_entry,
            "probe_used": probe_used,
            "should_abort": False,
        }
        return stage_result

    def _snapshot_server_process(self) -> Optional[Dict[str, Any]]:
        """
        Take a resource snapshot of the server process.

        :return: The snapshot, or None when there is no server process or it cannot be read
        """
        server_snapshot: Optional[Dict[str, Any]] = None
        if self.server_process:
            server_snapshot = ResourceMonitor.snapshot(self.server_process)
        return server_snapshot

    def _capture_before_snapshots(self, client_process: psutil.Process) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Capture and log the server, client and system resources before a stage.

        :param client_process: The client process
        :return: Dict with "server" (server snapshot, or None when not available) and "client" (client snapshot,
            or None)
        """
        before_server: Optional[Dict[str, Any]] = self._snapshot_server_process()
        if before_server:
            ResourceMonitor.log_snapshot("Server BEFORE", before_server)
        elif not self.args.client_only:
            logger.info("  Server BEFORE: not available (server not running)")

        before_client: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(client_process)
        if before_client:
            client_rss_megabytes: float = before_client.get("rss_megabytes")
            client_cpu_percent: float = before_client.get("cpu_percent")
            logger.info("  Client BEFORE: RSS %.1fM, CPU %.1f%%", client_rss_megabytes, client_cpu_percent)

        ResourceMonitor.log_system_memory("BEFORE")
        before_snapshots: Dict[str, Optional[Dict[str, Any]]] = {
            "server": before_server,
            "client": before_client,
        }
        return before_snapshots

    def _log_fire_info(self, actual_requests, monitor_resources, *, probe_result):
        """
        Log the 'Firing N requests' line with thread count.

        :param actual_requests: Number of requests this stage fires
        :param monitor_resources: When True and a local server process is known, the line also shows the
                                  server thread count
        :param probe_result: Result of the dry-run probe to count in this stage, or None
        """
        fire_seconds: float = time.time()
        fire_local_time: time.struct_time = time.localtime(fire_seconds)
        fire_ts: str = time.strftime("%H:%M:%S", fire_local_time)
        fire_threads = ""
        if monitor_resources and self.server_process:
            try:
                fire_threads = f"  threads: {self.server_process.num_threads()}"
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                logger.debug("Thread count unavailable: %s", exc)
        fire_label = actual_requests
        if probe_result is not None:
            fire_label = f"{actual_requests} ({actual_requests - 1} + 1 probe)"
        logger.info("\nFiring %s %s requests... [%s]%s", fire_label, self.args.agent, fire_ts, fire_threads)

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _collect_post_stage_data(
            self, actual_requests, monitor_resources,
            has_server_log,
            log_position, results, *,
            before_server, before_client,
            peak_client, settled_client,
            server_log_requests=None,
    ) -> Dict[str, Any]:
        """
        Settle, snapshot and analyze the server log after a stage.

        :param actual_requests: Number of requests sent in this stage
        :param monitor_resources: True to take the server snapshot after the stage
        :param has_server_log: True when the server log can be read
        :param log_position: Server log offset where the stage started, or None
        :param results: Request results of the stage
        :param before_server: Server snapshot before the stage, or None
        :param before_client: Client snapshot before the stage, or None
        :param peak_client: Peak client snapshot during the stage, or None
        :param settled_client: Client snapshot after the stage, or None
        :param server_log_requests: Number of stage requests in the server log, or None to use actual_requests
        :return: The dict from _analyze_server_log() plus "after_server" (server snapshot after the stage, or None)
        """
        after_server: Optional[Dict[str, Any]] = None

        if monitor_resources or has_server_log:
            time.sleep(self.args.settle_time)
            settle_end = time.strftime("%H:%M:%S", time.localtime(time.time()))
            logger.info("\n  Settle: waited %ss for server cleanup [%s]", self.args.settle_time, settle_end)

            after_server = self._snapshot_server_process()
            if after_server:
                ResourceMonitor.log_snapshot("Server AFTER", after_server)
            elif not self.args.client_only:
                logger.info("  Server AFTER: not available (server not running)")

        log_requests: int = actual_requests
        if server_log_requests is not None:
            log_requests = server_log_requests
        post_stage_data: Dict[str, Any] = self._analyze_server_log(has_server_log, log_position, results=results,
                                                                   actual_requests=log_requests)

        if before_server and after_server:
            self.resource_reporter.add_resource_row(f"{actual_requests}", before_server, after_server)

        if before_client and settled_client:
            self.resource_reporter.add_client_row(f"{actual_requests}", before_client, peak_client, settled_client)

        post_stage_data["after_server"] = after_server
        return post_stage_data

    def _analyze_server_log(self, has_server_log: bool, log_position: Optional[int], results: List[Dict[str, Any]],
                            actual_requests: int) -> Dict[str, Any]:
        """
        Analyze the server log of a stage, or report that it is not available.

        :param has_server_log: True when the server log can be read
        :param log_position: Server log offset where the stage started, or None
        :param results: Request results of the stage
        :param actual_requests: Number of stage requests expected in the server log
        :return: Dict with "server_counts" (request counts from the log) and "disconnections", "server_errors",
            "tool_warnings", "network_tokens" and "validation_events" (lists of dicts, empty without a server log)
        """
        server_counts: Dict[str, Any] = {}
        disconnections: List[Dict[str, str]] = []
        server_errors: List[Dict[str, str]] = []
        tool_warnings: List[Dict[str, str]] = []
        network_tokens: List[Dict[str, Any]] = []
        validation_events: List[Dict[str, Any]] = []
        if has_server_log:
            primary_start_pattern: str = self.profile.get_primary_start_pattern()
            primary_finish_pattern: str = self.profile.get_primary_finish_pattern()
            server_counts = self.log_monitor.count_requests_since(log_position, primary_start_pattern,
                                                                  primary_finish_pattern)
            disconnections = self.log_monitor.scan_disconnections_since(log_position,
                                                                        primary_start_pattern=primary_start_pattern)
            token_data: Dict[str, Dict[str, Any]] = self.log_monitor.parse_token_accounting_since(log_position)
            stage_results: List[Dict[str, Any]] = []
            request_result: Dict[str, Any]
            # Keep every result except request-0, the dry-run probe.
            for request_result in results:
                if request_result.get("request_id") != "request-0":
                    stage_results.append(request_result)
            if token_data:
                result: Dict[str, Any]
                # Keep the client token counts of each request under client_* keys.
                for result in stage_results:
                    result["client_total_tokens"] = result.get("total_tokens", 0)
                    result["client_prompt_tokens"] = result.get("prompt_tokens", 0)
                    result["client_completion_tokens"] = result.get("completion_tokens", 0)
                    result["client_llm_calls"] = result.get("llm_calls", 0)
            StageSummaryBuilder.attach_token_data(stage_results, token_data)
            network_tokens = self.log_monitor.parse_per_network_tokens_since(log_position)
            validation_events = self.log_monitor.parse_validation_events_since(log_position)
            StageSummaryBuilder.enrich_failure_reasons(results, validation_events)
            if token_data:
                logger.info("\n  Token usage (from server log):")
                TokenLogWriter.log_token_summary(
                    results, output_dir=self._output_dir,
                    network_tokens=network_tokens,
                    validation_events=validation_events,
                )
            OutputValidator.log_disconnections(disconnections)
            server_errors = self.log_monitor.scan_server_errors_since(log_position)
            OutputValidator.log_server_errors(server_errors)
            tool_warnings = self.log_monitor.scan_tool_warnings_since(log_position)
            OutputValidator.log_tool_warnings(tool_warnings)
            OutputValidator.log_server_validation(server_counts, actual_requests, self.args.agent)
        else:
            has_token_data: bool = False
            request_result: Dict[str, Any]
            # Look for any result that has client token counts.
            for request_result in results:
                if request_result.get("total_tokens"):
                    has_token_data = True
                    break
            if has_token_data:
                token_source: str = "HTTP token_accounting"
                logger.info("\n  Token usage (from %s):", token_source)
                TokenLogWriter.log_token_summary(results, output_dir=self._output_dir)
            if self.args.level != LoadTestConstants.LEVEL_MIN:
                logger.info("\n  Server-side validation: not available (no --server-log)")
        server_log_analysis: Dict[str, Any] = {
            "server_counts": server_counts,
            "disconnections": disconnections,
            "server_errors": server_errors,
            "tool_warnings": tool_warnings,
            "network_tokens": network_tokens,
            "validation_events": validation_events,
        }
        return server_log_analysis

    def _output_base(self) -> str:
        """
        Return the base output directory.

        The default is per-user because the temp directory is shared:
        whoever ran first would otherwise own ``load_test`` and lock
        everyone else out of it.

        :return: Path of the base output directory
        """
        if self.args.output_dir:
            return self.args.output_dir
        try:
            user = getpass.getuser()
        except (KeyError, OSError):
            # No passwd entry for this uid (some containers).
            user_id: int = os.getuid()
            user = str(user_id)
        user = re.sub(r"[^A-Za-z0-9._-]", "_", user)
        temp_dir: str = tempfile.gettempdir()
        return os.path.join(temp_dir, f"load_test_{user}")

    def _setup_test_log(self) -> None:
        """
        Create output directory and add a file handler for logging.
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base = self._output_base()
        neuro_san_version: Optional[str] = self.server_checker.resolve_ns_version()
        request_count: int = self.args.num_requests
        folder_name: str = RunNamer.run_folder_name(timestamp, self.args.host, neuro_san_version, request_count)
        self._output_dir = os.path.join(base, self.args.level, folder_name)
        os.makedirs(self._output_dir, exist_ok=True)
        self._run_log.open(self._output_dir)

    def _finalize_test_log(self, stage_summaries: List[Dict[str, Any]]) -> None:
        """
        Report the output directory and close the log handler.

        :param stage_summaries: One summary dict per stage
        """
        if self._output_dir is None:
            self._run_log.close()
            return
        has_failures: bool = False
        summary: Dict[str, Any]
        # Look for a stage with failed, timed-out or killed requests
        for summary in stage_summaries:
            counts: Dict[str, int] = summary.get("counts", {})
            if (counts.get(LoadTestConstants.STATUS_FAILED, 0) > 0
                    or counts.get(LoadTestConstants.STATUS_TIMEOUT, 0) > 0
                    or counts.get(LoadTestConstants.STATUS_KILLED, 0) > 0):
                has_failures = True
                break
        label: str = "OUTPUT FILES"
        if has_failures:
            label = "OUTPUT FILES (with failures)"
        logger.info("\n%s", Formatters.SEPARATOR_LINE)
        logger.info("  %s", label)
        logger.info("%s", Formatters.SEPARATOR_LINE)
        logger.info("  Directory:   %s", self._output_dir)
        json_path: str = os.path.join(self._output_dir, LoadTestConstants.RAW_RESULTS_FILE_NAME)
        if os.path.isfile(json_path):
            logger.info("  Raw results: %s", json_path)
        requests_dir: str = os.path.join(self._output_dir, LoadTestConstants.REQUESTS_DIR_NAME)
        if os.path.isdir(requests_dir):
            logger.info("  Requests:    %s", requests_dir)
        stdout_log_path: Optional[str] = self._run_log.get_path()
        if stdout_log_path is not None:
            logger.info("  Stdout log:  %s", stdout_log_path)
        self._history_recorder.log_existing_history_files()
        # Close the run log last so OUTPUT FILES is captured
        self._run_log.close()

    @staticmethod
    def _apply_level_defaults(args: argparse.Namespace, explicit_args: Set[str]) -> None:
        """
        Override argparse defaults with level-specific values.

        Only applies when the user did not explicitly set the flag.
        adv: LoadTestConstants.ADV_NUM_REQUESTS requests, LoadTestConstants.ADV_NUM_ROUNDS rounds (stress test).

        --full-concurrency matches workers to num-requests so every
        request fires at once.  Otherwise workers stay at the
        conservative --max-workers default and a warning is shown if
        max-workers < num-requests.

        :param args: Parsed arguments, updated in place
        :param explicit_args: Dest names the user passed on the command line
        """
        if args.level == LoadTestConstants.LEVEL_ADV:
            if "num_requests" not in explicit_args:
                args.num_requests = LoadTestConstants.ADV_NUM_REQUESTS
            if "num_rounds" not in explicit_args:
                args.num_rounds = LoadTestConstants.ADV_NUM_ROUNDS

        if "max_workers" not in explicit_args and args.full_concurrency:
            args.max_workers = args.num_requests

    @staticmethod
    def _apply_scale(args) -> None:
        """
        Multiply load parameters by --scale factor.

        Applied after level defaults so that both explicit
        values and level defaults are scaled uniformly.

        :param args: Parsed command-line arguments, scaled in place
        """
        factor = args.scale
        if factor <= 1:
            return
        args.num_requests *= factor
        args.max_workers *= factor
        args.request_timeout *= factor
        args.idle_timeout *= factor
        args.stage_timeout *= factor
        if args.total_timeout > 0:
            args.total_timeout *= factor

    def run(self) -> int:
        """
        Execute the full load test workflow.

        :return: The exit code: 0 when every request passes or the server-only monitor exits at its prompt,
                 1 on failures or an abort, 2 on Ctrl-C
        :raises SystemExit: When the arguments don't fit together
        :raises LoadTestAbortError: When the server can't be reached or the --server-log file is not found
        """
        level: str = self.args.level
        self.args.include_tokens = not self.args.no_tokens
        split_mode: bool = self.args.client_only or self.args.server_only
        if split_mode:
            level = LoadTestConstants.LEVEL_MIN
            self.args.level = LoadTestConstants.LEVEL_MIN
        elif level == LoadTestConstants.LEVEL_MIN:
            logger.error(
                "--level min requires --client-only or "
                "--server-only. For an all-in-one run use "
                "--level norm or --level adv.",
            )
            raise SystemExit(1)
        if self.args.client_only and self.args.server_only:
            logger.error("--client-only and --server-only are mutually exclusive.")
            raise SystemExit(1)
        if self.args.client_only and self.args.server_log is not None:
            logger.error("--client-only cannot be used with --server-log (server log is remote).")
            raise SystemExit(1)
        if self.args.server_only and self.args.server_log is None:
            self.args.server_log = "auto"
        if self.args.no_server_log and not self.args.server_only:
            self.args.server_log = None
        elif (self.args.server_log is None
                and not self.args.client_only
                and not self.args.server_only
                and self.args.host in LoadTestConstants.LOCAL_HOSTS
                and level != LoadTestConstants.LEVEL_MIN):
            self.args.server_log = EnvironmentValidator.try_auto_detect_server_log(self.args)
        if (level != LoadTestConstants.LEVEL_MIN
                and not self.args.client_only
                and not self.args.server_only
                and not self.args.no_server_log
                and self.args.server_log is None):
            if self.args.host not in LoadTestConstants.LOCAL_HOSTS:
                logger.error(
                    "--level %s needs a local server to read "
                    "server.log. Use --client-only for a remote "
                    "server, or pass --server-log <path>.",
                    level,
                )
                raise SystemExit(1)
            self.server_checker.confirm_no_server_log(level)
        self._apply_level_defaults(self.args, self.args.explicit_args)
        self._apply_scale(self.args)
        self.input_validator.validate_agent_name()
        EnvironmentValidator.validate_environment()
        stale_log_age_minutes: Optional[int] = self.server_checker.validate_server_log()

        stages = self.input_validator.resolve_stages()
        total_cap = self.input_validator.resolve_max_requests(stages)

        self._setup_test_log()
        if not self.args.server_only:
            self.server_checker.preflight_server_check()
            self.probe_result = (
                self.input_validator.confirm_cost(
                    stages, total_cap,
                    runner=self.runner,
                    output_dir=self._output_dir,
                    stale_log_age_minutes=stale_log_age_minutes,
                )
            )

        is_local: bool = self.args.host in LoadTestConstants.LOCAL_HOSTS
        monitor_resources: bool = level != LoadTestConstants.LEVEL_MIN or split_mode

        if self.args.client_only:
            logger.info("Client-only mode: skipping server process detection.")
        elif self.args.server_only:
            self.server_process = EnvironmentValidator.find_local_server(self.args)
        elif is_local:
            self.server_process = EnvironmentValidator.find_local_server(self.args)

        if self.args.server_log == "auto":
            self.args.server_log = EnvironmentValidator.auto_detect_server_log(self.server_process)

        self.server_log = self.args.server_log
        if self.server_log:
            self.log_monitor = ServerLogMonitor(self.server_log)

        if self.args.server_only:
            logger.info(
                "\nConfig: agent=%s, mode=server-only, "
                "num_requests=%s, host=%s, port=%s, "
                "stage_timeout=%ss",
                self.args.agent, self.args.num_requests,
                self.args.host, self.args.port,
                self.args.stage_timeout,
            )
            if self.server_log:
                logger.info("  server_log=%s", self.server_log)
            output_base: str = self._output_base()
            monitor_parts: Dict[str, Any] = {
                "server_process": self.server_process,
                "log_monitor": self.log_monitor,
                "history_recorder": self._history_recorder,
                "server_checker": self.server_checker,
            }
            server_only_monitor: ServerOnlyMonitor = ServerOnlyMonitor(self.args, self.profile, monitor_parts)
            return server_only_monitor.run(output_base)

        if not is_local:
            logger.info("Remote mode: targeting %s:%s", self.args.host, self.args.port)
            logger.info("  Process monitoring disabled (server is not local)")

        prompt_mode: str = "varied"
        if self.args.same_prompt:
            prompt_mode = "same"
        if self.args.allow_caching:
            prompt_mode = f"{prompt_mode} (caching allowed)"
        mode: str = "flat"
        if self.args.ramp:
            mode = "ramp"
        profile_source: str = self._profile_source()
        logger.info(
            "\nConfig: agent=%s, mode=%s, level=%s, "
            "stages=%s, rounds=%s, max_requests=%s, host=%s, port=%s, "
            "timeout=%ss, idle_timeout=%ss, "
            "stage_timeout=%ss, prompt_mode=%s, profile_source=%s",
            self.args.agent, mode, level, stages,
            self.args.num_rounds, total_cap,
            self.args.host, self.args.port, self.args.request_timeout,
            self.args.idle_timeout, self.args.stage_timeout,
            prompt_mode, profile_source,
        )
        if monitor_resources:
            logger.info("  settle_time=%ss", self.args.settle_time)
        if self.server_log:
            logger.info("  server_log=%s", self.server_log)
        else:
            logger.info("  server_log=none")
        if self.probe_result and self.probe_result.get("total_tokens"):
            probe_tokens: int = self.probe_result.get("total_tokens")
            logger.info("  tokens_per_request=%s (measured by probe)", f"{probe_tokens:,}")
        elif self.profile.get_estimated_tokens_per_request():
            estimated_tokens: int = self.profile.get_estimated_tokens_per_request()
            logger.info("  estimated_tokens_per_request=%s", f"{estimated_tokens:,}")

        stage_summaries: List[Dict[str, Any]] = []
        exit_code = 1
        pre_test_log_position: Optional[int] = None
        if self.server_log:
            pre_test_log_position = self.log_monitor.read_position()
        prev_sigint_handler = self._install_interrupt_handler()
        try:
            stage_summaries = self._run_all_stages(stages, total_cap)

            if self._aborted:
                exit_code = 1
            if self._interrupted:
                logger.warning(
                    "\n  Test interrupted (Ctrl-C) — the results "
                    "below cover only the requests that completed "
                    "before the interrupt.",
                )

            neuro_san_version: Optional[str] = self.server_checker.resolve_ns_version()
            summary_reporter = SummaryReporter(
                stage_summaries,
                neuro_san_version=neuro_san_version,
                client_token_source="HTTP token_accounting",
            )
            if len(stage_summaries) > 1:
                summary_reporter.log_ramp_summary(is_ramp=self.args.ramp)

            summary_reporter.log_overall_results()

            latency_analyzer = LatencyAnalyzer(stage_summaries)
            latency_analyzer.log_latency_analysis(is_ramp=self.args.ramp)
            latency_analyzer.log_degradation(is_ramp=self.args.ramp)

            server_chat_timing = []
            if self.server_log and pre_test_log_position is not None:
                server_chat_timing = self.log_monitor.parse_streaming_chat_timing_since(pre_test_log_position)

            if monitor_resources:
                total_client_reqs: int = 0
                total_server_calls: int = 0
                stage_summary: Dict[str, Any]
                # Add up the client requests and server calls of every stage.
                for stage_summary in stage_summaries:
                    total_client_reqs += stage_summary.get("concurrent", 0)
                    total_server_calls += stage_summary.get("total_started") or 0

                self.resource_reporter.log_combined_analysis(total_client_reqs, total_server_calls)
                disc_reporter = DisconnectionReporter(stage_summaries)
                disc_reporter.log_disconnection_summary()

            if level == LoadTestConstants.LEVEL_ADV:
                has_server_log = self.server_log is not None
                if has_server_log:
                    pool_analyzer = PoolAnalyzer(stage_summaries)
                    pool_analyzer.log_pool_reuse_analysis()
                else:
                    logger.info("\n  Pool reuse analysis: not available (no --server-log)")

            if self._interrupted:
                exit_code = 2
            elif not self._aborted:
                exit_code = self._check_results(stage_summaries)
            self._export_raw_json(stage_summaries, exit_code=exit_code)
            self._maybe_write_summary(stage_summaries, server_chat_timing)
            if self._interrupted:
                self._rename_interrupted()
        except KeyboardInterrupt:
            logger.info("\n  Interrupted — saving partial results...")
            self._export_raw_json(stage_summaries, exit_code=2)
            self._rename_interrupted()
            exit_code = 2
        finally:
            if prev_sigint_handler is not None:
                signal.signal(signal.SIGINT, prev_sigint_handler)
            self._history_recorder.append_client_record(stage_summaries, self.server_checker.get_server_ns_version())
            self._finalize_test_log(stage_summaries)

        return exit_code

    def was_interrupted(self) -> bool:
        """
        Return True if the run was stopped early by Ctrl-C.

        :return: True when Ctrl-C stops the run
        """
        return self._interrupted

    def _install_interrupt_handler(self):
        """
        Install a SIGINT handler that requests a graceful stop.

        The first Ctrl-C sets a cancel event so in-flight requests are
        killed and the completed ones are still summarized.  A second
        Ctrl-C restores the previous handler so the interpreter exits
        immediately.

        :return: The previous handler, or None if it could not be installed
                 (e.g. not on the main thread)
        """
        def _handle_sigint(_signum, _frame):
            """
            Stop gracefully on the first Ctrl-C, and restore the previous handler on the second.

            :param _signum: Signal number (not used)
            :param _frame: Current stack frame (not used)
            """
            # Nested to close over self and prev_handler, which the
            # signal callback needs to toggle graceful vs. forced stop;
            # signal.signal() takes a bare callable, not a bound method.
            if not self._cancel_event.is_set():
                self._cancel_event.set()
                self._interrupted = True
                logger.warning(
                    "\n  Ctrl-C received — stopping and gathering "
                    "results for completed requests (press Ctrl-C "
                    "again to force-quit)...",
                )
            elif prev_handler is not None:
                signal.signal(signal.SIGINT, prev_handler)

        try:
            prev_handler = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, _handle_sigint)
            return prev_handler
        except (ValueError, OSError):
            return None

    def _export_raw_json(self, stage_summaries: List[Dict[str, Any]], exit_code: int) -> None:
        """
        Save all test data as a single raw_results.json file.

        :param stage_summaries: One summary dict per stage
        :param exit_code: Exit code of the test
        """
        all_results: List[Dict[str, Any]] = self._collect_stage_results(stage_summaries)

        total_tokens: int = 0
        costs: List[float] = []
        latencies: List[float] = []
        passed: int = 0
        result: Dict[str, Any]
        # Collect the tokens, cost, latency and pass count of every request.
        for result in all_results:
            total_tokens += result.get("total_tokens", 0)
            costs.append(result.get("cost_usd", 0.0))
            latencies.append(result.get("elapsed", 0))
            if result.get("status") == LoadTestConstants.STATUS_CREATED:
                passed += 1
        total_cost: float = sum(costs)
        stage_elapsed: List[float] = []
        summary: Dict[str, Any]
        # Collect the elapsed time of every stage.
        for summary in stage_summaries:
            stage_elapsed.append(summary.get("elapsed", 0))
        total_elapsed: float = sum(stage_elapsed)
        total_requests: int = len(all_results)
        avg_latency: float = 0
        if total_requests:
            avg_latency = sum(latencies) / total_requests

        raw_data = {
            "test_metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "hostname": socket.gethostname(),
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "neuro_san_version": self.server_checker.resolve_ns_version(),
                "neuro_san_studio_version": ServerChecker.get_package_version(
                    "neuro_san_studio",
                ),
                "verdict": "PASSED" if exit_code == 0 else "FAILED",
                "exit_code": exit_code,
            },
            "config": {
                "agent": self.args.agent,
                "profile_path": self.args.profile_path,
                "level": self.args.level,
                "mode": "ramp" if self.args.ramp else "flat",
                "host": self.args.host,
                "port": self.args.port,
                "request_timeout": self.args.request_timeout,
                "idle_timeout": self.args.idle_timeout,
                "stage_timeout": self.args.stage_timeout,
                "total_timeout": self.args.total_timeout,
                "settle_time": self.args.settle_time,
                "max_workers": self.args.max_workers,
                "num_rounds": self.args.num_rounds,
                "num_requests": self.args.num_requests,
                "same_prompt": self.args.same_prompt,
                "allow_caching": self.args.allow_caching,
                "profile_source": self._profile_source(),
                "fixtures_hocon_dir": self.args.fixtures_hocon_dir,
                "hocon_files": self.hocon_files,
                "chat_filter": self.args.chat_filter,
                "server_log": self.server_log,
                "estimated_tokens_per_request": (
                    self.profile.get_estimated_tokens_per_request()
                ),
            },
            "aggregates": {
                "total_requests": total_requests,
                "passed": passed,
                "failed": total_requests - passed,
                "total_elapsed_seconds": round(total_elapsed, 2),
                "avg_latency_seconds": round(avg_latency, 2),
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 6),
            },
            "stage_summaries": stage_summaries,
            "resource_rows": self.resource_reporter.get_resource_snapshots(),
            "client_resource_rows": self.resource_reporter.get_client_snapshots(),
        }
        json_metadata: Dict[str, Any] = JsonMetadata.build()
        raw_data.update(json_metadata)
        json_path: str = os.path.join(self._output_dir, LoadTestConstants.RAW_RESULTS_FILE_NAME)
        with open(json_path, "w", encoding="utf-8") as json_file:
            json.dump(raw_data, json_file, indent=2, default=str)

    def _rename_interrupted(self) -> None:
        """
        Append _interrupted to the output directory name.
        """
        if self._output_dir is None:
            return
        new_path = self._output_dir + "_interrupted"
        try:
            os.rename(self._output_dir, new_path)
            self._output_dir = new_path
            logger.info("  Renamed output to: %s", new_path)
        except OSError as exc:
            logger.warning("  Could not rename output dir: %s", exc)

    def _maybe_write_summary(self, stage_summaries, server_chat_timing) -> None:
        """
        Write summary.txt for adv level only.

        With --no-dry-run: auto-write.  Otherwise prompt the user.

        :param stage_summaries: One summary dict per stage
        :param server_chat_timing: Server streaming_chat Start/Finish pairs for the test
        """
        if self.args.level != LoadTestConstants.LEVEL_ADV:
            return
        if not self.args.no_dry_run:
            if not Confirm.ask("\nSave summary.txt?"):
                return
        writer = SummaryFileWriter(stage_summaries, self.args, server_chat_timing=server_chat_timing)
        writer.write(self._output_dir)

    def _check_results(self, stage_summaries) -> int:
        """
        Log pass/fail verdict and return appropriate exit code.

        :param stage_summaries: One summary dict per stage
        :return: 0 when the test passes, 1 when it fails
        """
        all_results: List[Dict[str, Any]] = self._collect_stage_results(stage_summaries)
        total: int = len(all_results)
        passed: int = 0
        result: Dict[str, Any]
        # Count the requests that passed.
        for result in all_results:
            if result.get("status") == LoadTestConstants.STATUS_CREATED:
                passed += 1
        failed = total - passed

        if failed > 0:
            logger.info("\nLOAD TEST FAILED: %s/%s requests failed", failed, total)
            return 1

        logger.info("\nLOAD TEST PASSED: all %s requests completed successfully", total)
        return 0

    @staticmethod
    def _collect_stage_results(stage_summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Collect the request results of every stage into one list.

        :param stage_summaries: The summary dict of each stage, each with a "results" list
        :return: The results of all stages, in stage order
        """
        all_results: List[Dict[str, Any]] = []
        summary: Dict[str, Any]
        # Collect the results of every stage.
        for summary in stage_summaries:
            stage_results: List[Dict[str, Any]] = summary.get("results", [])
            all_results.extend(stage_results)
        return all_results

    @staticmethod
    def _agent_filter(args) -> Optional[List[str]]:
        """
        Split --compare-agent into a list of agent names.

        :param args: Parsed command-line arguments
        :return: The agent names, or None when --compare-agent is not set
        """
        if not args.compare_agent:
            return None
        agent_names: List[str] = []
        name: str
        # Keep each comma-separated agent name, without its spaces.
        for name in args.compare_agent.split(","):
            agent_names.append(name.strip())
        return agent_names

    @staticmethod
    def main() -> None:
        """
        Entry point for the load test script.
        """
        args = LoadTestArguments.parse_args(__doc__)
        if args.rebuild:
            ResultsRebuilder(args.rebuild, force=args.rebuild_all).run()
            return
        if args.trend:
            trend_agent_filter: Optional[List[str]] = LoadTestCli._agent_filter(args)
            TrendHistory(args.trend, agent_filter=trend_agent_filter).run()
            return
        if args.compare:
            agent_filter: Optional[List[str]] = LoadTestCli._agent_filter(args)
            run_filter: Optional[List[str]] = None
            if args.compare_runs:
                run_filter = []
                run_name: str
                # Keep each comma-separated run name, without its spaces.
                for run_name in args.compare_runs.split(","):
                    run_filter.append(run_name.strip())
            CrossRunComparison(
                args.compare,
                agent_filter=agent_filter,
                baseline_requests=args.compare_baseline,
                run_filter=run_filter,
            ).run()
            return
        try:
            load_test_cli = LoadTestCli(args)
            exit_code = load_test_cli.run()
        except LoadTestAbortError as abort_error:
            abort_exit_code: int = abort_error.get_exit_code()
            sys.exit(abort_exit_code)
        if load_test_cli.was_interrupted():
            # After Ctrl-C some worker threads (e.g. un-killable
            # in-thread HTTP requests) may still be blocked.  Results
            # are already printed and saved, so exit hard rather than
            # hang joining those threads at interpreter shutdown.
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(exit_code)
        sys.exit(exit_code)


if __name__ == "__main__":
    LoadTestCli.main()
