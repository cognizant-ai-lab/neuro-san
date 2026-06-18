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

# pylint: disable=too-many-lines
"""Generic load-test orchestrator for neuro-san agent networks.

See tests/load_tests/README.md for prerequisites, test levels, and
usage examples.
"""

import argparse
import importlib.metadata as _pkg_meta
import json
import logging
import os
import platform
import re
import socket
import sys
import tempfile
import time
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import psutil

from tests.load_tests.config import NetworkTokenEntry
from tests.load_tests.config import ResourceSnapshot
from tests.load_tests.config import ServerCounts
from tests.load_tests.config import StageSummary
from tests.load_tests.config import compute_amplification
from tests.load_tests.config import DEFAULT_IDLE_TIMEOUT_SECONDS
from tests.load_tests.config import DEFAULT_TIMEOUT_SECONDS
from tests.load_tests.config import LEVEL_ADV
from tests.load_tests.config import LEVEL_MIN
from tests.load_tests.config import LEVEL_NORM
from tests.load_tests.config import LOCAL_HOSTS
from tests.load_tests.config import STALE_LOG_THRESHOLD_SECONDS
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import THREAD_JOIN_TIMEOUT
from tests.load_tests.cost_estimator import CostEstimator
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.reporting.disconnection_reporter import DisconnectionReporter
from tests.load_tests.reporting.json_metadata import JsonMetadata
from tests.load_tests.reporting.latency_analyzer import LatencyAnalyzer
from tests.load_tests.reporting.pool_analyzer import PoolAnalyzer
from tests.load_tests.reporting.resource_reporter import ResourceReporter
from tests.load_tests.reporting.summary import SummaryReporter
from tests.load_tests.traffic.runner import TrafficRunner
from tests.load_tests.validation.environment_validator import EnvironmentValidator
from tests.load_tests.validation.input_validator import InputValidator
from tests.load_tests.validation.output_validator import OutputValidator

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class LoadTestOrchestrator:  # pylint: disable=too-many-instance-attributes
    """Orchestrates the full load test workflow."""

    @staticmethod
    def parse_args() -> argparse.Namespace:
        """Parse command-line arguments for the load test."""
        parser = argparse.ArgumentParser(
            description=(
                "Load-test neuro-san agent networks "
                "with real LLM calls."
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=__doc__,
        )

        parser.add_argument(
            "--agent",
            type=str,
            default="hello_world",
            help="Agent network name to test (default: hello_world). "
                 "Must be registered in the server's "
                 "AGENT_REGISTRY_PATH.",
        )
        parser.add_argument(
            "--profile-path",
            type=str,
            default=os.environ.get("LOAD_TEST_PROFILE_PATH"),
            help="Directory containing agent profile JSON files. "
                 "The filename is derived from --agent "
                 "(e.g. basic/smart_home → smart_home.json). "
                 "Without this, searches built-in profiles/. "
                 "Can also be set via LOAD_TEST_PROFILE_PATH "
                 "env var.",
        )
        parser.add_argument(
            "--project-root",
            type=str,
            default=None,
            help="Path to the project root where the server is "
                 "running from (e.g., /path/to/neuro-san-studio). "
                 "Used to find agent profiles at "
                 "{project-root}/tests/load_tests/prompts/profiles/. "
                 "Falls back to PYTHONPATH if not set.",
        )
        parser.add_argument(
            "--num-requests",
            type=int,
            default=3,
            help="Number of requests per round in flat mode "
                 "(default: 3). Ignored when --ramp is used.",
        )
        parser.add_argument(
            "--max-workers",
            type=int,
            default=3,
            help="Max concurrent workers in flat mode "
                 "(default: 3). At adv level with --yes, "
                 "auto-matches --num-requests unless "
                 "explicitly set. "
                 "Ignored when --ramp is used.",
        )
        parser.add_argument(
            "--num-rounds",
            type=int,
            default=1,
            help="Number of rounds in flat mode, or number of "
                 "times to repeat the full ramp sequence "
                 "(default: 1).",
        )
        parser.add_argument(
            "--ramp",
            action="store_true",
            default=False,
            help="Enable staged ramp-up mode. Runs escalating "
                 "concurrency stages instead of flat requests.",
        )
        parser.add_argument(
            "--stages",
            type=str,
            default=None,
            help="Comma-separated concurrency levels for ramp-up "
                 "mode (default: 10,30,50,100). "
                 "Only used with --ramp.",
        )
        parser.add_argument(
            "--max-requests",
            type=int,
            default=None,
            help="Hard cap on total requests across all "
                 "stages/rounds. Cost safeguard for real LLM calls."
                 " Default: sum(stages) * num_rounds.",
        )
        parser.add_argument(
            "--host",
            type=str,
            default="localhost",
            help="Neuro-san server host (default: localhost)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=8080,
            help="Neuro-san server port (default: 8080)",
        )
        parser.add_argument(
            "--request-timeout",
            type=int,
            default=DEFAULT_TIMEOUT_SECONDS,
            help="Hard timeout per request in seconds "
                 "(default: 1200). Safety net to prevent requests "
                 "from running forever.",
        )
        parser.add_argument(
            "--idle-timeout",
            type=int,
            default=DEFAULT_IDLE_TIMEOUT_SECONDS,
            help="Kill a request if no output for this many "
                 "seconds (default: 900). "
                 "Detects hanging requests.",
        )
        parser.add_argument(
            "--stage-timeout",
            type=int,
            default=1500,
            help="Hard timeout for an entire stage/round in "
                 "seconds (default: 1500 / 25 min). "
                 "Kills remaining in-flight requests when hit.",
        )
        parser.add_argument(
            "--total-timeout",
            type=int,
            default=0,
            help="Hard timeout for the entire load test in "
                 "seconds (default: 0 / disabled). "
                 "Kills the test run when exceeded.",
        )
        parser.add_argument(
            "--settle-time",
            type=int,
            default=15,
            help="Seconds to wait after each stage for cleanup "
                 "(default: 15)",
        )
        parser.add_argument(
            "--same-prompt",
            action="store_true",
            default=False,
            help="Use the same prompt for all requests "
                 "(collision stress test). Default is varied "
                 "prompts from the agent's prompt pool.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            default=False,
            help="Skip the cost confirmation prompt "
                 "(adv level only). Also auto-matches "
                 "--max-workers to --num-requests.",
        )
        parser.add_argument(
            "--server-log",
            nargs="?",
            const="auto",
            default=None,
            help="Enable server log analysis.  Without a path, "
                 "auto-detects the log from the server process.  "
                 "With a path, uses the given file.",
        )
        parser.add_argument(
            "--level",
            type=str,
            choices=[LEVEL_MIN, LEVEL_NORM, LEVEL_ADV],
            default=LEVEL_NORM,
            help="Test depth level (default: norm). "
                 "min: traffic + validation only. "
                 "norm: adds resource monitoring and "
                 "server log analysis (if --server-log given). "
                 "adv: adds JSON export and pool analysis "
                 "(defaults to 50 requests, 50 workers, "
                 "3 rounds unless overridden).",
        )
        parser.add_argument(
            "--monitor-resources",
            action="store_true",
            default=False,
            help="Enable psutil resource monitoring (CPU, memory, "
                 "threads, FDs) even at min level. "
                 "Automatically enabled at norm/adv.",
        )
        parser.add_argument(
            "--no-tokens",
            action="store_true",
            default=False,
            help="Disable per-request token accounting. By default "
                 "the load test passes --tokens to agent_cli at "
                 "all levels.",
        )
        parser.add_argument(
            "--skip-reservation-check",
            action="store_true",
            default=False,
            help="Skip reservation_id validation. A request is "
                 "marked CREATED if other success fields are "
                 "present, even without a reservation_id.",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Base directory for test output. Defaults to "
                 "/tmp/load_test/{level}/{timestamp}.",
        )
        args = parser.parse_args()
        # Track which args the user explicitly provided so
        # level-based defaults do not override them.
        explicit = set()
        for action in parser._actions:  # pylint: disable=protected-access
            for opt in action.option_strings:
                if opt in sys.argv:
                    explicit.add(action.dest)
                    break
        args._explicit = explicit  # pylint: disable=protected-access
        return args

    @staticmethod
    def _token_sort_key(rid) -> int:
        """Extract numeric suffix from a request_id for sorting."""
        match = re.search(r"(\d+)$", rid)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _attach_token_data(results, token_data) -> None:
        """Attach token accounting data to request results.

        The server assigns its own request_id numbering (e.g. request-3,
        request-4) which differs from the client's (request-1, request-2).
        Match by order: sort server entries by request_id number, then
        attach to client results in submission order.
        """
        if not token_data:
            return

        key_fn = LoadTestOrchestrator._token_sort_key
        sorted_entries = sorted(
            token_data.values(),
            key=lambda e: key_fn(e.get("request_id", "")),
        )
        sorted_results = sorted(
            results,
            key=lambda r: key_fn(r.get("request_id", "")),
        )

        for result, entry in zip(sorted_results, sorted_entries):
            result.update({
                "total_tokens": entry.get("total_tokens"),
                "prompt_tokens": entry.get("prompt_tokens"),
                "completion_tokens": entry.get("completion_tokens"),
                "llm_calls": entry.get("llm_calls"),
                "model": entry.get("model"),
                "cost_usd": CostEstimator.estimate(
                    entry.get("prompt_tokens", 0),
                    entry.get("completion_tokens", 0),
                    entry.get("model", "unknown"),
                ),
            })

    def __init__(self, args) -> None:
        """Initialize the orchestrator with parsed arguments."""
        self.args = args
        self.profile = AgentProfile.load(
            args.agent, args.profile_path, args.project_root,
        )
        self.server_proc = None
        self.server_log = args.server_log
        self.log_monitor = (
            ServerLogMonitor(self.server_log)
            if self.server_log else None
        )
        self.runner = TrafficRunner(args, self.profile)
        self.input_validator = InputValidator(args)
        self.resource_reporter = ResourceReporter()
        self.probe_result = None
        self._output_dir = None
        self._test_log_path = None
        self._test_log_handler = None
        self._aborted = False

    # pylint: disable=too-many-locals
    def _run_all_stages(self, stages, total_cap) -> List[StageSummary]:
        """Execute all stages of the load test, collecting data per stage."""
        monitor_resources = (
            self.args.level != LEVEL_MIN
            or self.args.monitor_resources
        )
        has_server_log = self.server_log is not None
        probe_result = self.probe_result

        stage_summaries: List[StageSummary] = []
        global_offset = 0
        total_sent = 0

        for round_num in range(1, self.args.num_rounds + 1):
            if self.args.num_rounds > 1:
                logger.info("\n%s", "#" * 60)
                logger.info("  ROUND %s of %s", round_num, self.args.num_rounds)
                logger.info("#" * 60)

            for stage_idx, num_concurrent in enumerate(stages):
                if total_sent >= total_cap:
                    total_planned = sum(stages) * self.args.num_rounds
                    logger.warning(
                        "\nWARNING: Reached --max-requests cap (%s). "
                        "Only %s of %s total planned requests completed.\n"
                        "         Use --max-requests %s to run all "
                        "planned requests.",
                        total_cap, total_sent, total_planned,
                        total_planned,
                    )
                    return stage_summaries

                remaining = total_cap - total_sent
                actual_requests = min(num_concurrent, remaining)

                summary, probe_used, should_abort = (
                    self._run_single_stage(
                        actual_requests=actual_requests,
                        num_concurrent=num_concurrent,
                        stage_num=stage_idx + 1,
                        round_num=round_num,
                        global_offset=global_offset,
                        monitor_resources=monitor_resources,
                        has_server_log=has_server_log,
                        probe_result=probe_result,
                    )
                )

                global_offset += actual_requests
                total_sent += actual_requests
                if probe_used:
                    probe_result = None
                stage_summaries.append(summary)
                if should_abort:
                    self._aborted = True
                    return stage_summaries

        return stage_summaries

    # pylint: disable=too-many-locals,too-many-statements,too-many-branches
    # pylint: disable=too-many-arguments
    def _run_single_stage(
            self, *, actual_requests, num_concurrent,
            stage_num, round_num, global_offset,
            monitor_resources, has_server_log,
            probe_result,
    ) -> Tuple[StageSummary, bool, bool]:
        """Execute one stage of the load test.

        Returns (stage_summary, probe_was_used, should_abort).
        """
        stage_workers = (
            self.args.max_workers
            if not self.args.ramp
            else actual_requests
        )

        logger.info("\n%s", "=" * 60)
        if self.args.ramp:
            stage_label = (
                f"[STAGE {stage_num}] "
                f"{actual_requests} requests "
                f"(max {stage_workers} workers)"
            )
            if self.args.num_rounds > 1:
                stage_label += f" (round {round_num})"
        else:
            stage_label = (
                f"{actual_requests} requests "
                f"(max {stage_workers} workers)"
            )
            if self.args.num_rounds > 1:
                stage_label += f" (round {round_num})"
        logger.info("  %s", stage_label)
        logger.info("=" * 60)

        if actual_requests < num_concurrent:
            logger.info(
                "  (Capped from %s to %s by --max-requests)",
                num_concurrent, actual_requests,
            )

        log_pos = (
            self.log_monitor.read_position()
            if has_server_log else None
        )

        before_server, before_client, client_proc = (
            self._capture_before_snapshots(monitor_resources)
        )

        self._log_fire_info(
            actual_requests, monitor_resources,
            probe_result=probe_result,
        )

        stop_event = None
        monitor = None
        if has_server_log:
            stop_event, monitor, _peak = (
                self.log_monitor.start_log_monitor(
                    log_pos,
                    actual_requests, time.time(),
                    client_proc=client_proc,
                    primary_start_pattern=(
                        self.profile.primary_start_pattern
                    ),
                )
            )

        # If a dry-run probe ran, inject it into stage 1
        stage_requests = actual_requests
        probe_used = probe_result is not None
        if probe_used:
            stage_requests = max(actual_requests - 1, 0)

        elapsed, results, peak_threads, peak_client_rss = (
            self.runner.run_stage(
                stage_requests, stage_workers,
                global_offset + (1 if probe_used else 0),
                server_proc=self.server_proc,
                client_proc=client_proc,
                output_dir=self._output_dir,
                stage_timeout=self.args.stage_timeout,
            )
        )

        if probe_used:
            results.insert(0, probe_result)

        if stop_event:
            stop_event.set()
        if monitor:
            monitor.join(timeout=THREAD_JOIN_TIMEOUT)

        peak_client = None
        settled_client = None
        if monitor_resources:
            peak_rss = peak_client_rss.value
            if peak_rss is not None:
                peak_client = {"rss": peak_rss}
            settled_client = ResourceMonitor.snapshot(
                client_proc,
            )
            if before_client and settled_client:
                rss_before = before_client.get("rss", 0)
                rss_settled = settled_client.get("rss", 0)
                rss_delta = rss_settled - rss_before
                logger.info(
                    "  Client SETTLED: RSS %.1fM (%+.1fM from before)",
                    rss_settled, rss_delta,
                )

        counts = OutputValidator.count_results(results)

        retries: Dict[str, int] = {}
        total_retries = 0
        amplification = 1.0
        if has_server_log:
            retries = self.log_monitor.count_retries_since(
                log_pos,
            )
            total_retries = sum(retries.values())
            amplification = compute_amplification(
                actual_requests, total_retries,
            )

        OutputValidator.log_stage_results(
            actual_requests, counts, elapsed,
            timeout=self.args.request_timeout,
            idle_timeout=self.args.idle_timeout,
            skip_reservation_check=(
                self.args.skip_reservation_check
            ),
        )
        should_abort = OutputValidator.check_permission_failures(
            results, self.args.agent,
        )
        if should_abort:
            summary_entry = self._build_stage_summary(
                stage_num=stage_num,
                round_num=round_num,
                actual_requests=actual_requests,
                counts=counts,
                elapsed=elapsed,
                retries=retries,
                total_retries=total_retries,
                amplification=amplification,
                results=results,
                server_counts={},
                disconnections=[],
                network_tokens=[],
                has_server_log=has_server_log,
                has_tokens=self.args.include_tokens,
                monitor_resources=monitor_resources,
                before_server=before_server,
                after_server=None,
                peak_threads=peak_threads,
            )
            return summary_entry, probe_used, True

        if has_server_log:
            OutputValidator.log_retry_activity(
                retries, total_retries, actual_requests,
            )
        elif monitor_resources:
            logger.info(
                "\n  Retry activity: not available "
                "(no --server-log)",
            )

        server_counts, disconnections, network_tokens, after_server = (
            self._collect_post_stage_data(
                actual_requests, monitor_resources,
                has_server_log,
                log_pos, results,
                before_server=before_server,
                before_client=before_client,
                peak_client=peak_client,
                settled_client=settled_client,
            )
        )

        summary_entry = self._build_stage_summary(
            stage_num=stage_num,
            round_num=round_num,
            actual_requests=actual_requests,
            counts=counts,
            elapsed=elapsed,
            retries=retries,
            total_retries=total_retries,
            amplification=amplification,
            results=results,
            server_counts=server_counts,
            disconnections=disconnections,
            network_tokens=network_tokens,
            has_server_log=has_server_log,
            has_tokens=self.args.include_tokens,
            monitor_resources=monitor_resources,
            before_server=before_server,
            after_server=after_server,
            peak_threads=peak_threads,
        )
        return summary_entry, probe_used, False

    def _capture_before_snapshots(self, monitor_resources):
        """Capture server and client resource snapshots before a stage."""
        before_server = None
        before_client = None
        client_proc = None
        if monitor_resources:
            before_server = (
                ResourceMonitor.snapshot(self.server_proc)
                if self.server_proc else None
            )
            if before_server:
                ResourceMonitor.log_snapshot(
                    "Server BEFORE", before_server,
                )

            client_proc = psutil.Process()
            before_client = ResourceMonitor.snapshot(
                client_proc,
            )
            if before_client:
                logger.info(
                    "  Client BEFORE: RSS %.1fM, CPU %.1f%%",
                    before_client.get("rss"),
                    before_client.get("cpu"),
                )
        return before_server, before_client, client_proc

    def _log_fire_info(self, actual_requests,
                       monitor_resources, *, probe_result):
        """Log the 'Firing N requests' line with thread count."""
        fire_ts = time.strftime(
            "%H:%M:%S", time.localtime(time.time()),
        )
        fire_threads = ""
        if monitor_resources and self.server_proc:
            try:
                fire_threads = (
                    f"  threads: {self.server_proc.num_threads()}"
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                logger.debug("Thread count unavailable: %s", exc)
        fire_label = actual_requests
        if probe_result is not None:
            fire_label = (
                f"{actual_requests} "
                f"({actual_requests - 1} + 1 probe)"
            )
        logger.info(
            "\nFiring %s %s requests... [%s]%s",
            fire_label, self.args.agent, fire_ts, fire_threads,
        )

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _collect_post_stage_data(
            self, actual_requests, monitor_resources,
            has_server_log,
            log_pos, results, *,
            before_server, before_client,
            peak_client, settled_client,
    ) -> Tuple[
        ServerCounts, List[Dict[str, str]],
        List[NetworkTokenEntry], Optional[ResourceSnapshot],
    ]:
        """Settle, snapshot, and analyze server log after a stage.

        Returns (server_counts, disconnections, network_tokens,
        after_server_snapshot).
        """
        server_counts: ServerCounts = {}
        disconnections: List[Dict[str, str]] = []
        network_tokens: List[NetworkTokenEntry] = []
        after_server = None

        if monitor_resources or has_server_log:
            settle_start = time.strftime(
                "%H:%M:%S", time.localtime(time.time()),
            )
            logger.info(
                "\n  Settle: waiting %ss for server cleanup... "
                "[%s]",
                self.args.settle_time, settle_start,
            )
            time.sleep(self.args.settle_time)
            settle_end = time.strftime(
                "%H:%M:%S", time.localtime(time.time()),
            )
            logger.info(
                "  Settle: done [%s]", settle_end,
            )

            after_server = (
                ResourceMonitor.snapshot(self.server_proc)
                if self.server_proc else None
            )
            if after_server:
                ResourceMonitor.log_snapshot(
                    "Server SETTLED", after_server,
                )

        server_counts, disconnections, network_tokens = (
            self._analyze_server_log(
                has_server_log,
                log_pos,
                results=results,
                actual_requests=actual_requests,
            )
        )

        if before_server and after_server:
            self.resource_reporter.add_resource_row(
                f"{actual_requests}",
                before_server, after_server,
            )

        if before_client and settled_client:
            self.resource_reporter.add_client_row(
                f"{actual_requests}",
                before_client,
                peak_client,
                settled_client,
            )

        return (
            server_counts, disconnections,
            network_tokens, after_server,
        )

    @staticmethod
    # pylint: disable=too-many-arguments
    def _build_stage_summary(
            *, stage_num, round_num, actual_requests,
            counts, elapsed, retries, total_retries,
            amplification, results, server_counts,
            disconnections, network_tokens,
            has_server_log, has_tokens,
            monitor_resources, before_server,
            after_server, peak_threads,
    ) -> StageSummary:
        """Assemble the stage summary dict."""
        summary_entry: StageSummary = {
            "stage": stage_num,
            "round": round_num,
            "concurrent": actual_requests,
            "counts": counts,
            "elapsed": elapsed,
            "retries": retries,
            "total_retries": total_retries,
            "amplification": amplification,
            "results": results,
            "primary_started": server_counts.get("primary_started"),
            "primary_finished": server_counts.get("primary_finished"),
            "total_started": server_counts.get("total_started"),
            "total_finished": server_counts.get("total_finished"),
            "disconnections": disconnections,
            "network_tokens": network_tokens,
            "has_server_log": has_server_log,
            "has_tokens": has_tokens,
        }
        if monitor_resources:
            if before_server:
                summary_entry["before_threads"] = (
                    before_server.get("threads")
                )
            if after_server:
                summary_entry["after_threads"] = (
                    after_server.get("threads")
                )
        if peak_threads.value is not None:
            summary_entry["peak_threads"] = (
                peak_threads.value
            )
        return summary_entry

    # pylint: disable=too-many-arguments
    def _analyze_server_log(
            self, has_server_log,
            log_pos, *, results, actual_requests,
    ) -> Tuple[
        ServerCounts, List[Dict[str, str]], List[NetworkTokenEntry],
    ]:
        """Analyze server log or report unavailability.

        Returns (server_counts, disconnections, network_tokens).
        """
        server_counts: ServerCounts = {}
        disconnections: List[Dict[str, str]] = []
        network_tokens: List[NetworkTokenEntry] = []
        if has_server_log:
            server_counts = (
                self.log_monitor.count_requests_since(
                    log_pos,
                    self.profile.primary_start_pattern,
                    self.profile.primary_finish_pattern,
                )
            )
            disconnections = (
                self.log_monitor.scan_disconnections_since(
                    log_pos,
                )
            )
            token_data = (
                self.log_monitor.parse_token_accounting_since(
                    log_pos,
                )
            )
            LoadTestOrchestrator._attach_token_data(
                results, token_data,
            )
            if token_data:
                logger.info(
                    "\n  Token usage (from server log):",
                )
                TrafficRunner.log_token_summary(results)
            network_tokens = (
                self.log_monitor.parse_per_network_tokens_since(
                    log_pos,
                )
            )
            OutputValidator.log_disconnections(disconnections)
            OutputValidator.log_server_validation(
                server_counts, actual_requests,
                self.args.agent,
            )
        else:
            has_token_data = any(
                r.get("total_tokens") for r in results
            )
            if has_token_data:
                logger.info(
                    "\n  Token usage "
                    "(from agent_cli --tokens):",
                )
                TrafficRunner.log_token_summary(results)
            if self.args.level != LEVEL_MIN:
                logger.info(
                    "\n  Server-side validation: "
                    "not available (no --server-log)",
                )
        return server_counts, disconnections, network_tokens

    def _setup_test_log(self) -> None:
        """Create output directory and add a file handler for logging."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base = self.args.output_dir or os.path.join(
            tempfile.gettempdir(), "load_test",
        )
        self._output_dir = os.path.join(
            base, self.args.level, timestamp,
        )
        os.makedirs(self._output_dir, exist_ok=True)
        self._test_log_path = os.path.join(self._output_dir, "load_test.log")
        self._test_log_handler = logging.FileHandler(
            self._test_log_path, encoding="utf-8",
        )
        self._test_log_handler.setLevel(logging.INFO)
        self._test_log_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(self._test_log_handler)

    def _finalize_test_log(self, stage_summaries) -> None:
        """Close the log handler and report the output directory."""
        if self._test_log_handler is not None:
            logging.getLogger().removeHandler(self._test_log_handler)
            self._test_log_handler.close()
        if self._output_dir is None:
            return
        has_failures = any(
            summary.get("counts", {}).get(STATUS_FAILED, 0) > 0
            or summary.get("counts", {}).get(STATUS_TIMEOUT, 0) > 0
            or summary.get("counts", {}).get(STATUS_KILLED, 0) > 0
            for summary in stage_summaries
        )
        label = (
            "OUTPUT FILES (with failures)"
            if has_failures else "OUTPUT FILES"
        )
        logger.info("\n%s", "=" * 60)
        logger.info("  %s", label)
        logger.info("=" * 60)
        logger.info("  Directory:   %s", self._output_dir)
        json_path = os.path.join(
            self._output_dir, "raw_results.json",
        )
        if os.path.isfile(json_path):
            logger.info("  Raw results: %s", json_path)

    def _validate_server_log(self) -> Optional[int]:
        """Validate --server-log path when provided.

        Skips validation when --server-log is used without a path
        (auto-detect mode, value is ``"auto"``).  At norm/adv levels
        without --server-log, logs a warning listing which features
        will be unavailable.

        Returns the stale log age in minutes, or None if not stale.
        """
        level = self.args.level
        server_log = self.args.server_log

        if server_log == "auto":
            return None

        if level == LEVEL_MIN and not server_log:
            return None

        if not server_log:
            logger.warning(
                "No --server-log provided at %s level.\n"
                "  The following will be unavailable:\n"
                "    - Retry counts and amplification factor\n"
                "    - Server-side request validation\n"
                "    - Client disconnection detection\n"
                "    - Per-agent-network token breakdown "
                "(server log only)\n"
                "  Resource monitoring (psutil) and aggregated "
                "token accounting (--tokens) still work.\n"
                "  To enable full analysis, add:\n"
                "    --server-log  (auto-detect)\n"
                "    --server-log logs/server.log",
                level,
            )
            return None

        if not os.path.isfile(server_log):
            logger.error(
                "Server log not found: %s", server_log,
            )
            sys.exit(1)

        mtime = os.path.getmtime(server_log)
        age_seconds = time.time() - mtime
        if age_seconds > STALE_LOG_THRESHOLD_SECONDS:
            return int(age_seconds // 60)
        return None

    @staticmethod
    def _apply_level_defaults(args, explicit_args) -> None:
        """Override argparse defaults with level-specific values.

        Only applies when the user did not explicitly set the flag.
        adv: 50 requests, 3 rounds (stress test).

        At adv level with --yes, workers auto-match num-requests
        (power user mode).  Otherwise workers default to 3
        (conservative) and a warning is shown if
        max-workers < num-requests.
        """
        if args.level == LEVEL_ADV:
            if "num_requests" not in explicit_args:
                args.num_requests = 50
            if "num_rounds" not in explicit_args:
                args.num_rounds = 3

        if ("max_workers" not in explicit_args
                and args.yes
                and args.level == LEVEL_ADV):
            args.max_workers = args.num_requests

    def run(self) -> int:
        """Execute the full load test workflow."""
        level = self.args.level
        self.args.include_tokens = not self.args.no_tokens
        if self.args.yes and level != LEVEL_ADV:
            logger.error(
                "--yes is only supported at adv level. "
                "At %s level, the cost confirmation prompt "
                "is required.",
                level,
            )
            raise SystemExit(1)
        explicit = getattr(self.args, "_explicit", set())
        self._apply_level_defaults(self.args, explicit)
        self.input_validator.validate_agent_name()
        EnvironmentValidator.validate_environment()
        stale_log_age = self._validate_server_log()

        stages = self.input_validator.resolve_stages()
        total_cap = self.input_validator.resolve_max_requests(
            stages,
        )

        self._setup_test_log()
        self.probe_result = self.input_validator.confirm_cost(
            stages, total_cap,
            runner=self.runner,
            output_dir=self._output_dir,
            stale_log_age=stale_log_age,
        )

        is_local = self.args.host in LOCAL_HOSTS
        monitor_resources = (
            level != LEVEL_MIN or self.args.monitor_resources
        )
        needs_server_proc = (
            (monitor_resources and is_local)
            or self.args.server_log is not None
        )

        if needs_server_proc and is_local:
            self.server_proc = (
                EnvironmentValidator.find_local_server(self.args)
            )

        if self.args.server_log == "auto":
            self.args.server_log = (
                EnvironmentValidator.auto_detect_server_log(
                    self.server_proc,
                )
            )

        self.server_log = self.args.server_log
        if self.server_log:
            self.log_monitor = ServerLogMonitor(self.server_log)

        if not monitor_resources:
            logger.info(
                "Level 'min': resource monitoring disabled. "
                "Use --monitor-resources to enable.",
            )
        elif not is_local:
            logger.info(
                "Remote mode: targeting %s:%s",
                self.args.host, self.args.port,
            )
            logger.info(
                "  Process monitoring disabled "
                "(server is not local)",
            )

        prompt_mode = "same" if self.args.same_prompt else "varied"
        mode = "ramp" if self.args.ramp else "flat"
        logger.info(
            "\nConfig: agent=%s, mode=%s, level=%s, "
            "stages=%s, rounds=%s, max_requests=%s, host=%s, port=%s, "
            "timeout=%ss, idle_timeout=%ss, "
            "stage_timeout=%ss, prompt_mode=%s",
            self.args.agent, mode, level, stages,
            self.args.num_rounds, total_cap,
            self.args.host, self.args.port, self.args.request_timeout,
            self.args.idle_timeout, self.args.stage_timeout,
            prompt_mode,
        )
        if monitor_resources:
            logger.info("  settle_time=%ss", self.args.settle_time)
        if self.server_log:
            logger.info("  server_log=%s", self.server_log)
        else:
            logger.info("  server_log=none")
        if self.profile.estimated_tokens_per_request:
            logger.info(
                "  estimated_tokens_per_request=%s",
                f"{self.profile.estimated_tokens_per_request:,}",
            )

        stage_summaries: List[StageSummary] = []
        exit_code = 1
        try:
            stage_summaries = self._run_all_stages(
                stages, total_cap,
            )

            if self._aborted:
                exit_code = 1
                self._export_raw_json(
                    stage_summaries, exit_code=exit_code,
                )
                return exit_code

            summary_reporter = SummaryReporter(stage_summaries)
            if len(stage_summaries) > 1:
                summary_reporter.log_ramp_summary(
                    is_ramp=self.args.ramp,
                )

            summary_reporter.log_overall_results()

            latency_analyzer = LatencyAnalyzer(stage_summaries)
            latency_analyzer.log_latency_analysis(
                is_ramp=self.args.ramp,
            )
            latency_analyzer.log_degradation(
                is_ramp=self.args.ramp,
            )
            latency_analyzer.log_concurrency_timeline()

            if monitor_resources:
                total_client_reqs = sum(
                    s.get("concurrent", 0) for s in stage_summaries
                )
                total_server_calls = sum(
                    s.get("total_started") or 0 for s in stage_summaries
                )

                self.resource_reporter.log_resource_analysis(
                    total_client_reqs,
                    total_server_calls,
                )
                disc_reporter = DisconnectionReporter(
                    stage_summaries,
                )
                disc_reporter.log_disconnection_summary()
                self.resource_reporter.log_client_analysis(
                    total_client_reqs,
                )

            if level == LEVEL_ADV:
                has_server_log = self.server_log is not None
                if has_server_log:
                    pool_analyzer = PoolAnalyzer(stage_summaries)
                    pool_analyzer.log_pool_reuse_analysis()
                else:
                    logger.info(
                        "\n  Pool reuse analysis: "
                        "not available (no --server-log)",
                    )

            exit_code = self._check_results(stage_summaries)
            self._export_raw_json(
                stage_summaries, exit_code=exit_code,
            )
        finally:
            self._finalize_test_log(stage_summaries)

        return exit_code

    def _export_raw_json(self, stage_summaries, *,
                         exit_code) -> None:
        """Save all test data as a single raw_results.json file."""
        all_results = []
        for s in stage_summaries:
            all_results.extend(s.get("results", []))

        total_tokens = sum(
            r.get("total_tokens", 0) for r in all_results
        )
        total_cost = sum(
            r.get("cost_usd", 0.0) for r in all_results
        )
        total_elapsed = sum(
            s.get("elapsed", 0) for s in stage_summaries
        )
        total_requests = len(all_results)
        passed = sum(
            1 for r in all_results
            if r.get("status") == STATUS_CREATED
        )

        raw_data = {
            "test_metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "hostname": socket.gethostname(),
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "neuro_san_version": self._get_package_version(
                    "neuro_san",
                ),
                "neuro_san_studio_version": self._get_package_version(
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
                "server_log": self.server_log,
                "estimated_tokens_per_request": (
                    self.profile.estimated_tokens_per_request
                ),
            },
            "aggregates": {
                "total_requests": total_requests,
                "passed": passed,
                "failed": total_requests - passed,
                "total_elapsed_seconds": round(total_elapsed, 2),
                "avg_latency_seconds": round(
                    total_elapsed / total_requests, 2,
                ) if total_requests > 0 else 0,
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 6),
            },
            "stage_summaries": stage_summaries,
            "resource_rows": [
                {"before": row[1], "after": row[2]}
                for row in self.resource_reporter.resource_rows
            ],
            "client_resource_rows": [
                {
                    "before": row[1],
                    "peak": row[2],
                    "settled": row[3],
                }
                for row in self.resource_reporter.client_rows
            ],
        }
        raw_data.update(JsonMetadata.build())
        json_path = os.path.join(self._output_dir, "raw_results.json")
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(raw_data, fh, indent=2, default=str)

    def _check_results(self, stage_summaries) -> int:
        """Log pass/fail verdict and return appropriate exit code."""
        all_results = []
        for s in stage_summaries:
            all_results.extend(s.get("results", []))
        total = len(all_results)
        passed = sum(
            1 for r in all_results
            if r.get("status") == STATUS_CREATED
        )
        failed = total - passed

        if failed > 0:
            logger.info(
                "\nLOAD TEST FAILED: %s/%s requests failed",
                failed, total,
            )
            return 1

        logger.info(
            "\nLOAD TEST PASSED: all %s requests completed successfully",
            total,
        )
        return 0

    @staticmethod
    def _get_package_version(package_name) -> Optional[str]:
        """Return the installed version of a package, or None."""
        try:
            return _pkg_meta.version(package_name)
        except _pkg_meta.PackageNotFoundError:
            return None

    @staticmethod
    def main() -> None:
        """Entry point for the load test script."""
        args = LoadTestOrchestrator.parse_args()
        orchestrator = LoadTestOrchestrator(args)
        sys.exit(orchestrator.run())


if __name__ == "__main__":
    LoadTestOrchestrator.main()
