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
from time import localtime
from time import sleep
from time import strftime
from time import struct_time
from time import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from psutil import Process

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.reporting.duration_parser import DurationParser
from tests.load_tests.reporting.resource_reporter import ResourceReporter
from tests.load_tests.reporting.stage_summary_builder import StageSummaryBuilder
from tests.load_tests.reporting.token_log_writer import TokenLogWriter
from tests.load_tests.validation.output_validator import OutputValidator


class StageDataCollector:
    """
    Collects the data of one load-test stage after its requests finish: the settle wait, the server snapshot
    after the stage, the resource rows, and the server log analysis.
    """

    # Request id of the dry-run probe, which is not one of the stage requests.
    PROBE_REQUEST_ID: str = "request-0"

    def __init__(self, args: Namespace, collector_parts: Dict[str, Any]) -> None:
        """
        Keep the run's arguments and the parts the stage data is read from.

        :param args: Parsed command-line arguments
        :param collector_parts: A dict with the following keys:
            "profile"            The AgentProfile
            "log_monitor"        The ServerLogMonitor, or None
            "resource_reporter"  The ResourceReporter
            "server_process"     The local server process, or None
            "output_dir"         The run's output directory
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.args: Namespace = args
        self.profile: AgentProfile = collector_parts.get("profile")
        self.log_monitor: Optional[ServerLogMonitor] = collector_parts.get("log_monitor")
        self.resource_reporter: ResourceReporter = collector_parts.get("resource_reporter")
        self.server_process: Optional[Process] = collector_parts.get("server_process")
        self._output_dir: Optional[str] = collector_parts.get("output_dir")

    def collect_post_stage_data(self, post_stage_inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Settle, snapshot and analyze the server log after a stage.

        :param post_stage_inputs: A dict with the following keys:
            "actual_requests"      Number of requests sent in this stage
            "monitor_resources"    True to take the server snapshot after the stage
            "has_server_log"       True when the server log can be read
            "log_position"         Server log offset where the stage started, or None
            "results"              Request results of the stage
            "before_server"        Server snapshot before the stage, or None
            "before_client"        Client snapshot before the stage, or None
            "peak_client"          Peak client snapshot, or None
            "settled_client"       Client snapshot after the stage, or None
            "server_log_requests"  Number of stage requests in the server log, or None to use actual_requests
        :return: A dict with the following keys:
            "server_counts"      See _analyze_server_log()
            "disconnections"     See _analyze_server_log()
            "server_errors"      See _analyze_server_log()
            "tool_warnings"      See _analyze_server_log()
            "network_tokens"     See _analyze_server_log()
            "validation_events"  See _analyze_server_log()
            "after_server"       Server snapshot after the stage, or None
        """
        actual_requests: int = post_stage_inputs.get("actual_requests")
        has_server_log: bool = post_stage_inputs.get("has_server_log")
        server_log_requests: Optional[int] = post_stage_inputs.get("server_log_requests")
        after_server: Optional[Dict[str, Any]] = None
        if post_stage_inputs.get("monitor_resources") or has_server_log:
            after_server = self._settle_and_snapshot()

        log_requests: int = actual_requests
        if server_log_requests is not None:
            log_requests = server_log_requests
        log_position: Optional[int] = post_stage_inputs.get("log_position")
        results: List[Dict[str, Any]] = post_stage_inputs.get("results")
        post_stage_data: Dict[str, Any] = self._analyze_server_log(has_server_log, log_position, results, log_requests)
        self._add_resource_rows(post_stage_inputs, after_server)
        post_stage_data["after_server"] = after_server
        return post_stage_data

    def snapshot_server_process(self) -> Optional[Dict[str, Any]]:
        """
        Take a resource snapshot of the server process.

        :return: The snapshot, or None when there is no server process or it cannot be read
        """
        server_snapshot: Optional[Dict[str, Any]] = None
        if self.server_process:
            server_snapshot = ResourceMonitor.snapshot(self.server_process)
        return server_snapshot

    def _settle_and_snapshot(self) -> Optional[Dict[str, Any]]:
        """
        Wait --settle-time for the server to clean up, then take and log the server snapshot.

        :return: The server snapshot after the stage, or None when it is not available
        """
        sleep(self.args.settle_time)
        settle_end_seconds: float = time()
        settle_end_local: struct_time = localtime(settle_end_seconds)
        settle_end: str = strftime("%H:%M:%S", settle_end_local)
        settle_text: str = DurationParser.format_minutes_seconds(self.args.settle_time)
        self.logger.info("\n  Settle: waited %s for server cleanup [%s]", settle_text, settle_end)

        after_server: Optional[Dict[str, Any]] = self.snapshot_server_process()
        if after_server:
            ResourceMonitor.log_snapshot("Server AFTER", after_server)
        elif not self.args.client_only:
            self.logger.info("  Server AFTER: not available (server not running)")
        return after_server

    def _add_resource_rows(self, post_stage_inputs: Dict[str, Any], after_server: Optional[Dict[str, Any]]) -> None:
        """
        Add the server and client resource rows of a stage when their snapshots are available.

        :param post_stage_inputs: The dict of collect_post_stage_data()
        :param after_server: Server snapshot after the stage, or None
        """
        actual_requests: int = post_stage_inputs.get("actual_requests")
        stage_label: str = f"{actual_requests}"
        before_server: Optional[Dict[str, Any]] = post_stage_inputs.get("before_server")
        before_client: Optional[Dict[str, Any]] = post_stage_inputs.get("before_client")
        settled_client: Optional[Dict[str, Any]] = post_stage_inputs.get("settled_client")
        if before_server and after_server:
            self.resource_reporter.add_resource_row(stage_label, before_server, after_server)

        if before_client and settled_client:
            peak_client: Optional[Dict[str, Any]] = post_stage_inputs.get("peak_client")
            self.resource_reporter.add_client_row(stage_label, before_client, peak_client, settled_client)

    def _analyze_server_log(self, has_server_log: bool, log_position: Optional[int], results: List[Dict[str, Any]],
                            actual_requests: int) -> Dict[str, Any]:
        """
        Analyze the server log of a stage, or report that it is not available.

        :param has_server_log: True when the server log can be read
        :param log_position: Server log offset where the stage started, or None
        :param results: Request results of the stage
        :param actual_requests: Number of stage requests expected in the server log
        :return: A dict with the following keys; the lists are empty without a server log:
            "server_counts"      Request counts from the log
            "disconnections"     List of client disconnections
            "server_errors"      List of server errors
            "tool_warnings"      List of tool warnings
            "network_tokens"     List of token entries per sub-network
            "validation_events"  List of validation events
        """
        server_log_analysis: Dict[str, Any] = {
            "server_counts": {},
            "disconnections": [],
            "server_errors": [],
            "tool_warnings": [],
            "network_tokens": [],
            "validation_events": [],
        }
        if has_server_log:
            server_log_analysis = self._analyze_stage_log(log_position, results, actual_requests)
        else:
            self._log_client_token_usage(results)
            if self.args.level != LoadTestConstants.LEVEL_MIN:
                self.logger.info("\n  Server-side validation: not available (no --server-log)")
        return server_log_analysis

    def _analyze_stage_log(self, log_position: Optional[int], results: List[Dict[str, Any]],
                           actual_requests: int) -> Dict[str, Any]:
        """
        Read the request counts, disconnections, tokens, validation events, errors and tool warnings of a stage
        from the server log, and log them.

        :param log_position: Server log offset where the stage started, or None
        :param results: Request results of the stage
        :param actual_requests: Number of stage requests expected in the server log
        :return: The dict of _analyze_server_log()
        """
        primary_start_pattern: str = self.profile.get_primary_start_pattern()
        primary_finish_pattern: str = self.profile.get_primary_finish_pattern()
        server_counts: Dict[str, Any] = self.log_monitor.count_requests_since(log_position, primary_start_pattern,
                                                                              primary_finish_pattern)
        disconnections: List[Dict[str, str]] = self.log_monitor.scan_disconnections_since(
            log_position, primary_start_pattern=primary_start_pattern)
        token_data: Dict[str, Dict[str, Any]] = self.log_monitor.parse_token_accounting_since(log_position)
        StageDataCollector._attach_token_data(results, token_data)
        network_tokens: List[Dict[str, Any]] = self.log_monitor.parse_per_network_tokens_since(log_position)
        validation_events: List[Dict[str, Any]] = self.log_monitor.parse_validation_events_since(log_position)
        StageSummaryBuilder.enrich_failure_reasons(results, validation_events)
        if token_data:
            self.logger.info("\n  Token usage (from server log):")
            token_log_writer: TokenLogWriter = TokenLogWriter()
            token_log_writer.log_token_summary(
                results, output_dir=self._output_dir,
                network_tokens=network_tokens,
                validation_events=validation_events,
            )
        OutputValidator.log_disconnections(disconnections)
        server_errors: List[Dict[str, str]] = self.log_monitor.scan_server_errors_since(log_position)
        OutputValidator.log_server_errors(server_errors)
        tool_warnings: List[Dict[str, str]] = self.log_monitor.scan_tool_warnings_since(log_position)
        OutputValidator.log_tool_warnings(tool_warnings)
        OutputValidator.log_server_validation(server_counts, actual_requests, self.args.agent)
        server_log_analysis: Dict[str, Any] = {
            "server_counts": server_counts,
            "disconnections": disconnections,
            "server_errors": server_errors,
            "tool_warnings": tool_warnings,
            "network_tokens": network_tokens,
            "validation_events": validation_events,
        }
        return server_log_analysis

    @staticmethod
    def _attach_token_data(results: List[Dict[str, Any]], token_data: Dict[str, Dict[str, Any]]) -> None:
        """
        Keep the client token counts under client_* keys, then attach the server log token counts.

        :param results: Request results of the stage
        :param token_data: Token counts from the server log, by request id
        """
        stage_results: List[Dict[str, Any]] = []
        request_result: Dict[str, Any]
        # Keep every result except request-0, the dry-run probe.
        for request_result in results:
            if request_result.get("request_id") != StageDataCollector.PROBE_REQUEST_ID:
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

    def _log_client_token_usage(self, results: List[Dict[str, Any]]) -> None:
        """
        Log the client token usage of a stage when there is no server log.

        :param results: Request results of the stage
        """
        has_token_data: bool = False
        request_result: Dict[str, Any]
        # Look for any result that has client token counts.
        for request_result in results:
            if request_result.get("total_tokens"):
                has_token_data = True
                break
        if has_token_data:
            token_source: str = LoadTestConstants.CLIENT_TOKEN_SOURCE
            self.logger.info("\n  Token usage (from %s):", token_source)
            token_log_writer: TokenLogWriter = TokenLogWriter()
            token_log_writer.log_token_summary(results, output_dir=self._output_dir)
