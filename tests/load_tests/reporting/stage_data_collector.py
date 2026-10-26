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

from tests.load_tests.duration import DurationParser
from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.reporting.resource_reporter import ResourceReporter
from tests.load_tests.reporting.stage_summary_builder import StageSummaryBuilder
from tests.load_tests.reporting.token_log_writer import TokenLogWriter
from tests.load_tests.validation.output_validator import OutputValidator


class StageDataCollector:
    """
    Collects the data of one load-test stage after its requests finish: the settle wait, the server snapshot
    after the stage, the resource rows, and the server log analysis.
    """

    LOGGER: Logger = getLogger(__name__)

    def __init__(self, args: Namespace, collector_parts: Dict[str, Any]) -> None:
        """
        Keep the run's arguments and the parts the stage data is read from.

        :param args: Parsed command-line arguments
        :param collector_parts: A dict with "profile" (the AgentProfile), "log_monitor" (the ServerLogMonitor, or
            None), "resource_reporter" (the ResourceReporter), "server_process" (the local server process, or None)
            and "output_dir" (the run's output directory)
        """
        self.args: Namespace = args
        self.profile: AgentProfile = collector_parts.get("profile")
        self.log_monitor: Optional[ServerLogMonitor] = collector_parts.get("log_monitor")
        self.resource_reporter: ResourceReporter = collector_parts.get("resource_reporter")
        self.server_process: Optional[Process] = collector_parts.get("server_process")
        self._output_dir: Optional[str] = collector_parts.get("output_dir")

    def collect_post_stage_data(  # pylint: disable=too-many-locals
            self, post_stage_inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Settle, snapshot and analyze the server log after a stage.

        :param post_stage_inputs: A dict with "actual_requests" (number of requests sent in this stage),
            "monitor_resources" (True to take the server snapshot after the stage), "has_server_log" (True when the
            server log can be read), "log_position" (server log offset where the stage started, or None), "results"
            (request results of the stage), "before_server" and "before_client" (snapshots before the stage, or
            None), "peak_client" (peak client snapshot, or None), "settled_client" (client snapshot after the stage,
            or None) and "server_log_requests" (number of stage requests in the server log, or None to use
            actual_requests)
        :return: A dict with "server_counts", "disconnections", "server_errors", "tool_warnings", "network_tokens"
            and "validation_events" (see _analyze_server_log()), plus "after_server" (server snapshot after the
            stage, or None)
        """
        actual_requests: int = post_stage_inputs.get("actual_requests")
        monitor_resources: bool = post_stage_inputs.get("monitor_resources")
        has_server_log: bool = post_stage_inputs.get("has_server_log")
        log_position: Optional[int] = post_stage_inputs.get("log_position")
        results: List[Dict[str, Any]] = post_stage_inputs.get("results")
        before_server: Optional[Dict[str, Any]] = post_stage_inputs.get("before_server")
        before_client: Optional[Dict[str, Any]] = post_stage_inputs.get("before_client")
        peak_client: Optional[Dict[str, Any]] = post_stage_inputs.get("peak_client")
        settled_client: Optional[Dict[str, Any]] = post_stage_inputs.get("settled_client")
        server_log_requests: Optional[int] = post_stage_inputs.get("server_log_requests")
        after_server: Optional[Dict[str, Any]] = None

        if monitor_resources or has_server_log:
            sleep(self.args.settle_time)
            settle_end_seconds: float = time()
            settle_end_local: struct_time = localtime(settle_end_seconds)
            settle_end: str = strftime("%H:%M:%S", settle_end_local)
            settle_text: str = DurationParser.format_minutes_seconds(self.args.settle_time)
            StageDataCollector.LOGGER.info("\n  Settle: waited %s for server cleanup [%s]", settle_text, settle_end)

            after_server = self.snapshot_server_process()
            if after_server:
                ResourceMonitor.log_snapshot("Server AFTER", after_server)
            elif not self.args.client_only:
                StageDataCollector.LOGGER.info("  Server AFTER: not available (server not running)")

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

    def snapshot_server_process(self) -> Optional[Dict[str, Any]]:
        """
        Take a resource snapshot of the server process.

        :return: The snapshot, or None when there is no server process or it cannot be read
        """
        server_snapshot: Optional[Dict[str, Any]] = None
        if self.server_process:
            server_snapshot = ResourceMonitor.snapshot(self.server_process)
        return server_snapshot

    def _analyze_server_log(  # pylint: disable=too-many-locals
            self, has_server_log: bool, log_position: Optional[int], results: List[Dict[str, Any]],
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
                StageDataCollector.LOGGER.info("\n  Token usage (from server log):")
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
                StageDataCollector.LOGGER.info("\n  Token usage (from %s):", token_source)
                TokenLogWriter.log_token_summary(results, output_dir=self._output_dir)
            if self.args.level != LoadTestConstants.LEVEL_MIN:
                StageDataCollector.LOGGER.info("\n  Server-side validation: not available (no --server-log)")
        server_log_analysis: Dict[str, Any] = {
            "server_counts": server_counts,
            "disconnections": disconnections,
            "server_errors": server_errors,
            "tool_warnings": tool_warnings,
            "network_tokens": network_tokens,
            "validation_events": validation_events,
        }
        return server_log_analysis
