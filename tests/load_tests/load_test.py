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
"""Generic load-test orchestrator for neuro-san agent networks.

See tests/load_tests/README.md for prerequisites, test levels, and
usage examples.
"""

import argparse
import gzip
import importlib.metadata as _pkg_meta
import json
import logging
import os
import platform
import re
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import psutil

from tests.load_tests.config import NetworkTokenEntry
from tests.load_tests.config import ValidationEvent
from tests.load_tests.config import ResourceSnapshot
from tests.load_tests.config import ServerCounts
from tests.load_tests.config import StageSummary
from tests.load_tests.config import Formatters
from tests.load_tests.config import DEFAULT_IDLE_TIMEOUT_SECONDS
from tests.load_tests.config import DEFAULT_TIMEOUT_SECONDS
from tests.load_tests.config import LEVEL_ADV
from tests.load_tests.config import LEVEL_MIN
from tests.load_tests.config import LEVEL_NORM
from tests.load_tests.config import LOCAL_HOSTS
from tests.load_tests.config import SOCKET_CHECK_TIMEOUT
from tests.load_tests.config import STALE_LOG_THRESHOLD_SECONDS
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import HEARTBEAT_INTERVAL_SECONDS
from tests.load_tests.config import HISTORY_FILE_NAME
from tests.load_tests.config import HISTORY_UNKNOWN_FILE_NAME
from tests.load_tests.config import HISTORY_THRESHOLDS_SECONDS
from tests.load_tests.config import THREAD_JOIN_TIMEOUT
from tests.load_tests.cost_estimator import CostEstimator
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.reporting.cross_run_comparison import CrossRunComparison
from tests.load_tests.reporting.rebuild_results import ResultsRebuilder
from tests.load_tests.reporting.disconnection_reporter import DisconnectionReporter
from tests.load_tests.reporting.json_metadata import JsonMetadata
from tests.load_tests.reporting.latency_analyzer import LatencyAnalyzer
from tests.load_tests.reporting.pool_analyzer import PoolAnalyzer
from tests.load_tests.reporting.resource_reporter import ResourceReporter
from tests.load_tests.reporting.summary import SummaryReporter
from tests.load_tests.reporting.summary_file_writer import SummaryFileWriter
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
            help="Neuro-san server port (default: 8080 for "
                 "http, 443 for https unless overridden)",
        )
        parser.add_argument(
            "--https",
            action="store_true",
            default=False,
            help="Use HTTPS/TLS to reach the server. "
                 "Default is plain HTTP. When set and --port "
                 "is not given, the port defaults to 443.",
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
            "--archive-server-log",
            action="store_true",
            default=False,
            help="Gzip and copy the server log into the "
                 "output directory after the test completes. "
                 "Requires --server-log.",
        )
        parser.add_argument(
            "--client-only",
            action="store_true",
            default=False,
            help="Client-only mode for split-machine testing. "
                 "Fires requests and monitors client RSS and "
                 "system memory. Skips server process "
                 "detection and server log analysis. "
                 "Mutually exclusive with --server-only.",
        )
        parser.add_argument(
            "--http-client",
            action="store_true",
            default=False,
            help="Use direct HTTP requests instead of "
                 "spawning agent_cli subprocesses. "
                 "Drastically reduces client memory "
                 "(~1 MB vs ~96 MB per concurrent request). "
                 "Implies --client-only.",
        )
        parser.add_argument(
            "--server-only",
            action="store_true",
            default=False,
            help="Server-only mode for split-machine testing. "
                 "Monitors the server process and reads the "
                 "server log while a remote client fires "
                 "requests. Does not fire requests itself. "
                 "Mutually exclusive with --client-only.",
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
                 "adv: adds pool analysis "
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
            "--scale",
            type=int,
            default=1,
            help="Multiplier for load parameters. Scales "
                 "--num-requests, --max-workers, "
                 "--request-timeout, --idle-timeout, "
                 "--stage-timeout, and --total-timeout "
                 "by this factor. "
                 "--max-requests auto-adjusts. "
                 "Integer only (default: 1).",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Base directory for test output. Defaults to "
                 "/tmp/load_test/{level}/{timestamp}.",
        )
        parser.add_argument(
            "--history-file",
            type=str,
            default=None,
            help="Append-only JSONL file recording one trend record "
                 "per client run (completion counts under fixed time "
                 "thresholds + neuro-san version) for plotting over "
                 "time. Defaults to <output-base>/history.jsonl.",
        )
        parser.add_argument(
            "--compare",
            type=str,
            default=None,
            metavar="DIR",
            help="Skip load test; scan DIR for previous "
                 "raw_results.json files and print a "
                 "cross-run comparison table.",
        )
        parser.add_argument(
            "--compare-agent",
            type=str,
            default=None,
            metavar="NAME",
            help="When used with --compare, show only runs "
                 "for this agent (e.g. hello_world). "
                 "Comma-separated for multiple agents. "
                 "Without this, tables are grouped by agent.",
        )
        parser.add_argument(
            "--compare-baseline",
            type=int,
            default=0,
            metavar="N",
            help="When used with --compare, only show runs "
                 "with at least N requests. The smallest "
                 "remaining run becomes the baseline for "
                 "percentage deltas.",
        )
        parser.add_argument(
            "--compare-runs",
            type=str,
            default=None,
            metavar="FOLDERS",
            help="When used with --compare, show only "
                 "these specific run folders. "
                 "Comma-separated folder names.",
        )
        parser.add_argument(
            "--rebuild",
            type=str,
            default=None,
            metavar="DIR",
            help="Reconstruct raw_results.json from the "
                 "request output files in DIR. Useful for "
                 "runs interrupted by Ctrl+C.",
        )
        parser.add_argument(
            "--rebuild-all",
            action="store_true",
            default=False,
            help="When used with --rebuild on a parent "
                 "directory, rebuild ALL runs including "
                 "those that already have raw_results.json.",
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
        # When targeting https and no explicit port was given,
        # default to the standard TLS port.
        if args.https and "port" not in explicit:
            args.port = 443
        return args

    @staticmethod
    def _token_sort_key(rid) -> int:
        """Extract numeric suffix from a request_id for sorting."""
        match = re.search(r"(\d+)$", rid)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _enrich_failure_reasons(results, validation_events):
        """Append validation fix cycle info to failure reasons."""
        if not validation_events:
            return
        by_rid = {
            e.get("request_id"): e
            for e in validation_events
        }
        for result in results:
            rid = result.get("request_id", "")
            event = by_rid.get(rid)
            if event is None:
                continue
            fix_cycles = event.get("fix_cycles", 0)
            if fix_cycles <= 0:
                continue
            existing = result.get("failure_reason") or ""
            suffix = (
                f" ({fix_cycles} validation fix"
                f" cycle(s))"
            )
            result["failure_reason"] = existing + suffix

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
                "reporting_agent": entry.get("reporting_agent"),
                "server_request_id": entry.get("request_id"),
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
        self._interrupted = False
        self._cancel_event = threading.Event()
        self._server_ns_version = None

    # pylint: disable=too-many-locals
    def _run_all_stages(self, stages, total_cap) -> List[StageSummary]:
        """Execute all stages of the load test, collecting data per stage."""
        monitor_resources = (
            self.args.level != LEVEL_MIN
            or self.args.monitor_resources
        )
        has_server_log = self.server_log is not None
        probe_result = self.probe_result
        only_stage = (
            len(stages) == 1 and self.args.num_rounds == 1
        )

        stage_summaries: List[StageSummary] = []
        global_offset = 0
        total_sent = 0
        test_start = time.time()

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

                if self._total_timeout_reached(test_start):
                    self._aborted = True
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
                        only_stage=only_stage,
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

    def _total_timeout_reached(self, test_start) -> bool:
        """Check if total-timeout has been exceeded.

        Returns True and logs a warning when the elapsed time since
        test_start exceeds --total-timeout (0 means disabled).
        """
        limit = self.args.total_timeout
        if limit <= 0:
            return False
        elapsed = time.time() - test_start
        if elapsed < limit:
            return False
        logger.warning(
            "\n  ABORT: --total-timeout (%ss) reached after %.0fs.\n"
            "  Stopping test and reporting available results.",
            limit, elapsed,
        )
        return True

    # pylint: disable=too-many-locals,too-many-statements,too-many-branches
    # pylint: disable=too-many-arguments
    def _run_single_stage(
            self, *, actual_requests, num_concurrent,
            stage_num, round_num, global_offset,
            monitor_resources, has_server_log,
            probe_result, only_stage=False,
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
                    output_dir=self._output_dir,
                )
            )

        # If a dry-run probe ran, inject it into stage 1
        stage_requests = actual_requests
        probe_used = probe_result is not None
        if probe_used:
            stage_requests = max(actual_requests - 1, 0)

        before_sys_mem_pct = psutil.virtual_memory().percent

        (elapsed, results, peak_threads, peak_client_rss,
         peak_server_rss, peak_sys_mem_pct, peak_sys_cpu,
         server_died, interrupted) = (
            self.runner.run_stage(
                stage_requests, stage_workers,
                global_offset + (1 if probe_used else 0),
                server_proc=self.server_proc,
                client_proc=client_proc,
                output_dir=self._output_dir,
                stage_timeout=self.args.stage_timeout,
                cancel_event=self._cancel_event,
                log_monitor=self.log_monitor,
                primary_start_pattern=(
                    self.profile.primary_start_pattern
                ),
            )
        )
        if interrupted:
            self._interrupted = True

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

        counts = OutputValidator.count_results(results)

        retries: Dict[str, int] = {}
        total_retries = 0
        amplification = 1.0
        if has_server_log:
            retries = self.log_monitor.count_retries_since(
                log_pos,
            )
            total_retries = sum(retries.values())
            amplification = Formatters.compute_amplification(
                stage_requests, total_retries,
            )

        OutputValidator.log_stage_results(
            actual_requests, counts, elapsed,
            timeout=self.args.request_timeout,
            idle_timeout=self.args.idle_timeout,
            skip_reservation_check=(
                self.args.skip_reservation_check
            ),
            show_counts=not only_stage,
        )
        should_abort = server_died or interrupted
        if not should_abort:
            should_abort = OutputValidator.check_permission_failures(
                results, self.args.agent,
            )
        if not should_abort:
            should_abort = OutputValidator.check_timeout_abort(counts)
        if should_abort:
            after_sys_mem_pct = (
                psutil.virtual_memory().percent
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
                server_counts={},
                disconnections=[],
                network_tokens=[],
                validation_events=[],
                has_server_log=has_server_log,
                has_tokens=self.args.include_tokens,
                monitor_resources=monitor_resources,
                before_server=before_server,
                after_server=None,
                peak_threads=peak_threads,
                peak_server_rss=peak_server_rss,
                before_client=before_client,
                peak_client=peak_client,
                settled_client=settled_client,
                before_sys_mem_pct=before_sys_mem_pct,
                after_sys_mem_pct=after_sys_mem_pct,
                peak_sys_mem_pct=peak_sys_mem_pct,
                peak_sys_cpu=peak_sys_cpu,
            )
            return summary_entry, probe_used, True

        if has_server_log:
            OutputValidator.log_retry_activity(
                retries, total_retries, stage_requests,
            )

        server_counts, disconnections, network_tokens, \
            validation_events, after_server = (
                self._collect_post_stage_data(
                    actual_requests, monitor_resources,
                    has_server_log,
                    log_pos, results,
                    before_server=before_server,
                    before_client=before_client,
                    peak_client=peak_client,
                    settled_client=settled_client,
                    server_log_requests=stage_requests,
                )
            )

        after_sys_mem_pct = psutil.virtual_memory().percent

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
            validation_events=validation_events,
            has_server_log=has_server_log,
            has_tokens=self.args.include_tokens,
            monitor_resources=monitor_resources,
            before_server=before_server,
            after_server=after_server,
            peak_threads=peak_threads,
            peak_server_rss=peak_server_rss,
            before_client=before_client,
            peak_client=peak_client,
            settled_client=settled_client,
            before_sys_mem_pct=before_sys_mem_pct,
            after_sys_mem_pct=after_sys_mem_pct,
            peak_sys_mem_pct=peak_sys_mem_pct,
            peak_sys_cpu=peak_sys_cpu,
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
            elif not self.args.client_only:
                logger.info(
                    "  Server BEFORE: not available"
                    " (server not running)",
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

            mem = psutil.virtual_memory()
            used_mb = (mem.total - mem.available) / (1024 ** 2)
            avail_gb = mem.available / (1024 ** 3)
            total_gb = mem.total / (1024 ** 3)
            logger.info(
                "  System BEFORE: %.0f%% used"
                " (%.0fM used / %.1fG free / %.1fG total)",
                mem.percent, used_mb, avail_gb, total_gb,
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
            server_log_requests=None,
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
            time.sleep(self.args.settle_time)
            settle_end = time.strftime(
                "%H:%M:%S", time.localtime(time.time()),
            )
            logger.info(
                "\n  Settle: waited %ss for server cleanup [%s]",
                self.args.settle_time, settle_end,
            )

            after_server = (
                ResourceMonitor.snapshot(self.server_proc)
                if self.server_proc else None
            )
            if after_server:
                ResourceMonitor.log_snapshot(
                    "Server AFTER", after_server,
                )
            elif not self.args.client_only:
                logger.info(
                    "  Server AFTER: not available"
                    " (server not running)",
                )

        server_counts, disconnections, network_tokens, \
            validation_events = (
                self._analyze_server_log(
                    has_server_log,
                    log_pos,
                    results=results,
                    actual_requests=(
                        server_log_requests
                        if server_log_requests is not None
                        else actual_requests
                    ),
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
            network_tokens, validation_events,
            after_server,
        )

    @staticmethod
    # pylint: disable=too-many-arguments
    def _build_stage_summary(
            *, stage_num, round_num, actual_requests,
            counts, elapsed, retries, total_retries,
            amplification, results, server_counts,
            disconnections, network_tokens,
            validation_events,
            has_server_log, has_tokens,
            monitor_resources, before_server,
            after_server, peak_threads,
            peak_server_rss,
            before_client=None,
            peak_client=None,
            settled_client=None,
            before_sys_mem_pct=None,
            after_sys_mem_pct=None,
            peak_sys_mem_pct=None,
            peak_sys_cpu=None,
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
            "validation_events": validation_events,
            "has_server_log": has_server_log,
            "has_tokens": has_tokens,
        }
        if monitor_resources:
            if before_server:
                summary_entry["before_threads"] = (
                    before_server.get("threads")
                )
                summary_entry["before_server_rss"] = (
                    before_server.get("rss")
                )
            if after_server:
                summary_entry["after_threads"] = (
                    after_server.get("threads")
                )
                summary_entry["after_server_rss"] = (
                    after_server.get("rss")
                )
        if peak_threads.value is not None:
            summary_entry["peak_threads"] = (
                peak_threads.value
            )
        if peak_server_rss.value is not None:
            summary_entry["peak_server_rss"] = (
                peak_server_rss.value
            )
        if before_client:
            summary_entry["before_client_rss"] = (
                before_client.get("rss")
            )
        if settled_client:
            summary_entry["after_client_rss"] = (
                settled_client.get("rss")
            )
        if peak_client:
            summary_entry["peak_client_rss"] = (
                peak_client.get("rss")
            )
        if before_sys_mem_pct is not None:
            summary_entry["before_sys_mem_pct"] = (
                before_sys_mem_pct
            )
        if after_sys_mem_pct is not None:
            summary_entry["after_sys_mem_pct"] = (
                after_sys_mem_pct
            )
        if (peak_sys_mem_pct is not None
                and peak_sys_mem_pct.value is not None):
            peak_data = peak_sys_mem_pct.value
            summary_entry["peak_sys_mem_pct"] = (
                peak_data["pct"]
            )
            summary_entry["peak_sys_mem_avail_gb"] = (
                peak_data["avail_gb"]
            )
        if (peak_sys_cpu is not None
                and peak_sys_cpu.value is not None):
            summary_entry["peak_sys_cpu"] = peak_sys_cpu.value
        return summary_entry

    # pylint: disable=too-many-arguments
    def _analyze_server_log(
            self, has_server_log,
            log_pos, *, results, actual_requests,
    ) -> Tuple[
        ServerCounts, List[Dict[str, str]],
        List[NetworkTokenEntry], List[ValidationEvent],
    ]:
        """Analyze server log or report unavailability.

        Returns (server_counts, disconnections, network_tokens,
        validation_events).
        """
        server_counts: ServerCounts = {}
        disconnections: List[Dict[str, str]] = []
        network_tokens: List[NetworkTokenEntry] = []
        validation_events: List[ValidationEvent] = []
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
                    primary_start_pattern=(
                        self.profile.primary_start_pattern
                    ),
                )
            )
            token_data = (
                self.log_monitor.parse_token_accounting_since(
                    log_pos,
                )
            )
            stage_results = [
                r for r in results
                if r.get("request_id") != "request-0"
            ]
            LoadTestOrchestrator._attach_token_data(
                stage_results, token_data,
            )
            network_tokens = (
                self.log_monitor.parse_per_network_tokens_since(
                    log_pos,
                )
            )
            validation_events = (
                self.log_monitor.parse_validation_events_since(
                    log_pos,
                )
            )
            LoadTestOrchestrator._enrich_failure_reasons(
                results, validation_events,
            )
            if token_data:
                logger.info(
                    "\n  Token usage (from server log):",
                )
                TrafficRunner.log_token_summary(
                    results, output_dir=self._output_dir,
                    network_tokens=network_tokens,
                    validation_events=validation_events,
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
                TrafficRunner.log_token_summary(
                    results, output_dir=self._output_dir,
                )
            if self.args.level != LEVEL_MIN:
                logger.info(
                    "\n  Server-side validation: "
                    "not available (no --server-log)",
                )
        return (
            server_counts, disconnections,
            network_tokens, validation_events,
        )

    def _setup_test_log(self) -> None:
        """Create output directory and add a file handler for logging."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base = self.args.output_dir or os.path.join(
            tempfile.gettempdir(), "load_test",
        )
        folder_name = self._run_folder_name(
            timestamp, self.args.num_requests,
        )
        self._output_dir = os.path.join(
            base, self.args.level, folder_name,
        )
        os.makedirs(self._output_dir, exist_ok=True)
        self._test_log_path = os.path.join(self._output_dir, "stdout.log")
        self._test_log_handler = logging.FileHandler(
            self._test_log_path, encoding="utf-8",
        )
        self._test_log_handler.setLevel(logging.INFO)
        self._test_log_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(self._test_log_handler)

    def _preflight_server_check(self) -> None:
        """Abort before firing if the target server is unreachable.

        A quick TCP connect to --host:--port catches "server not
        found" (connection refused / DNS failure / host down) so a
        whole run's worth of requests is not fired at nothing.
        """
        host = self.args.host
        port = self.args.port
        if EnvironmentValidator.is_port_open(host, port):
            logger.info(
                "  Preflight: server %s:%s reachable.", host, port,
            )
            self._server_ns_version = self._fetch_server_version()
            if self._server_ns_version:
                logger.info(
                    "  Preflight: server neuro-san version %s.",
                    self._server_ns_version,
                )
            else:
                logger.info(
                    "  Preflight: server version unavailable "
                    "(no /healthz response).",
                )
            return
        scheme = (
            "https" if getattr(self.args, "https", False) else "http"
        )
        logger.error(
            "ABORT: server %s:%s (%s) is unreachable — "
            "not firing any requests.\n"
            "  Check --host/--port/--https, or start the server.",
            host, port, scheme,
        )
        raise SystemExit(1)

    def _fetch_server_version(self) -> Optional[str]:
        """Return the server's neuro-san version via its /healthz API.

        Queries ``<scheme>://<host>:<port>/healthz`` (the same HTTP
        endpoint the client already reaches, so it works remotely
        without any access to the server machine) and reads
        ``versions['neuro-san']``.  Returns None if the endpoint is
        unreachable or unparseable (e.g. an older/gRPC-only server).
        """
        scheme = (
            "https" if getattr(self.args, "https", False) else "http"
        )
        url = f"{scheme}://{self.args.host}:{self.args.port}/healthz"
        try:
            with urllib.request.urlopen(
                url, timeout=SOCKET_CHECK_TIMEOUT,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload.get("versions", {}).get("neuro-san")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.debug(
                "Could not fetch server version from %s: %s", url, exc,
            )
            return None

    def _finalize_test_log(self, stage_summaries) -> None:
        """Report the output directory and close the log handler."""
        if self._output_dir is None:
            if self._test_log_handler is not None:
                logging.getLogger().removeHandler(
                    self._test_log_handler,
                )
                self._test_log_handler.close()
            return
        self._archive_server_log()
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
        gz_path = os.path.join(
            self._output_dir, "server.log.gz",
        )
        if os.path.isfile(gz_path):
            size_mb = os.path.getsize(gz_path) / (1024 * 1024)
            logger.info(
                "  Server log:  %s (%.1fM)",
                gz_path, size_mb,
            )
        if self._test_log_path is not None:
            logger.info(
                "  Stdout log:  %s", self._test_log_path,
            )
        for history_path in (
            self._history_path(),
            self._history_path(successful=False),
        ):
            if os.path.isfile(history_path):
                logger.info("  History:     %s", history_path)
        # Close handler last so OUTPUT FILES is captured
        if self._test_log_handler is not None:
            logging.getLogger().removeHandler(
                self._test_log_handler,
            )
            self._test_log_handler.close()

    def _archive_server_log(self) -> None:
        """Gzip the server log into the output directory."""
        if not self.args.archive_server_log:
            return
        if not self.server_log or not os.path.isfile(
            self.server_log,
        ):
            logger.warning(
                "  --archive-server-log: no server log to"
                " archive (missing --server-log or file"
                " not found)",
            )
            return
        gz_path = os.path.join(
            self._output_dir, "server.log.gz",
        )
        with open(self.server_log, "rb") as f_in, \
                gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

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

    @staticmethod
    def _apply_scale(args) -> None:
        """Multiply load parameters by --scale factor.

        Applied after level defaults so that both explicit
        values and level defaults are scaled uniformly.
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

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _server_only_primary_pairs(
            self, log_pos, pri_start_re,
    ) -> List[Dict]:
        """Primary-agent streaming_chat Start/Finish pairs since log_pos.

        Returns the subset of parsed pairs whose agent matches the
        primary (front-man) agent, each with ``start_ts``,
        ``finish_ts``, and ``duration``.  Empty on read error or when
        no primary request has completed yet.
        """
        if self.log_monitor is None:
            return []
        try:
            pairs = (
                self.log_monitor
                .parse_streaming_chat_timing_since(log_pos)
            )
        except (OSError, ValueError):
            return []
        primary = []
        for pair in pairs:
            agent = pair.get("agent", "")
            start_line = f"Start {agent}/streaming_chat"
            if pri_start_re.search(start_line):
                primary.append(pair)
        return primary

    def _server_only_dur_stats(
            self, log_pos, pri_start_re,
    ) -> str:
        """Cumulative server-side min/avg/max for the primary agent.

        Parses primary streaming_chat Start/Finish pairs seen since
        the round's log position and formats them.  Returns "n/a"
        until at least one request has completed.
        """
        durations = [
            float(p["duration"])
            for p in self._server_only_primary_pairs(
                log_pos, pri_start_re,
            )
            if isinstance(p.get("duration"), (int, float))
            and p["duration"] > 0
        ]
        return Heartbeat.format_dur_stats(durations)

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _server_only_heartbeat(
            self, received, expected, completed,
            elapsed, now, snap, cur_mem,
            dur_stats="n/a",
            cur_sys_cpu=None, peak_sys_cpu=None,
    ) -> None:
        """Log a periodic heartbeat during server-only monitoring."""
        cur_used_mb = (
            (cur_mem.total - cur_mem.available)
            / (1024 ** 2)
        )
        cur_avail_gb = cur_mem.available / (1024 ** 3)
        rss_str = ""
        threads_str = ""
        if snap:
            rss_str = (
                f"  RSS: {snap.get('rss', 0):.0f}M"
            )
            threads_str = (
                f"  threads: "
                f"{snap.get('threads', 0)}"
            )
        ts = time.strftime(
            "%H:%M:%S", time.localtime(now),
        )
        if elapsed < 60:
            fmt_elapsed = f"{elapsed:.0f}s"
        else:
            mins = int(elapsed) // 60
            fmt_elapsed = f"{elapsed:.0f}s ({mins}m)"
        in_flight = max(0, received - completed)
        if received >= expected:
            progress_str = (
                f" {expected} recv"
                f"  {completed}/{expected} done"
                f"  {in_flight} in-flight"
            )
        else:
            progress_str = (
                f" {received}/{expected} recv"
                f"  {completed} done"
                f"  {in_flight} in-flight"
            )
        sys_cpu_str = ""
        if cur_sys_cpu is not None:
            peak_val = (
                peak_sys_cpu
                if peak_sys_cpu is not None
                else cur_sys_cpu
            )
            sys_cpu_str = (
                f"  syscpu: {cur_sys_cpu:.0f}%"
                f" (peak {peak_val:.0f}%)"
            )
        logger.info(
            "  [heartbeat] %s [%s]%s  dur/server: %s%s%s"
            "  sysmem: %.0f%% (%.0fM used"
            " / %.1fG free)%s",
            fmt_elapsed, ts,
            progress_str,
            dur_stats,
            threads_str, rss_str,
            cur_mem.percent, cur_used_mb,
            cur_avail_gb,
            sys_cpu_str,
        )

    def _run_server_only_monitor(self) -> int:
        """Interactive server-only monitoring loop.

        Prompts the user for the expected request count, then
        monitors the server log until all requests arrive (or
        timeout / Ctrl-C).  After each round, reports results,
        writes raw_results.json, archives the server log, and
        loops back for another round.  Only exits on Ctrl-C
        at the prompt.
        """
        primary_start_pattern = (
            self.profile.primary_start_pattern
        )
        pri_start_re = re.compile(primary_start_pattern)
        primary_finish_pattern = (
            self.profile.primary_finish_pattern
        )
        pri_finish_re = re.compile(
            primary_finish_pattern,
        )
        round_num = 0

        while True:
            try:
                answer = input(
                    "\nHow many requests will the"
                    " client send? ",
                )
            except (KeyboardInterrupt, EOFError):
                logger.info(
                    "\n  Exiting server-only monitor.",
                )
                return 0

            answer = answer.strip()
            if not answer:
                continue
            try:
                expected = int(answer)
            except ValueError:
                logger.error(
                    "  Invalid number: %s", answer,
                )
                continue
            if expected <= 0:
                logger.error(
                    "  Number must be positive.",
                )
                continue

            round_num += 1
            self._run_server_only_round(
                expected, round_num,
                pri_start_re, pri_finish_re,
            )

    def _setup_round_output_dir(
            self, expected, round_num,
    ) -> str:
        """Create an output directory for a server-only round."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base = self.args.output_dir or os.path.join(
            tempfile.gettempdir(), "load_test",
        )
        folder_name = self._run_folder_name(timestamp, expected)
        round_dir = os.path.join(
            base, "server_only", folder_name,
        )
        os.makedirs(round_dir, exist_ok=True)
        return round_dir

    def _run_server_only_round(
            self, expected, round_num,
            pri_start_re, pri_finish_re,
    ) -> None:
        """Execute one round of server-only monitoring.

        Wraps the round body with a per-round ``stdout.log`` file
        handler so each server-only round captures its own console
        output (heartbeats + summary) in its output directory.
        """
        round_dir = self._setup_round_output_dir(
            expected, round_num,
        )
        log_pos = self.log_monitor.read_position()
        round_log_path = os.path.join(round_dir, "stdout.log")
        round_handler = logging.FileHandler(
            round_log_path, encoding="utf-8",
        )
        round_handler.setLevel(logging.INFO)
        round_handler.setFormatter(
            logging.Formatter("%(message)s"),
        )
        root_logger = logging.getLogger()
        root_logger.addHandler(round_handler)
        try:
            self._server_only_round_body(
                expected, round_num,
                pri_start_re, pri_finish_re,
                round_dir, log_pos, round_log_path,
            )
        finally:
            root_logger.removeHandler(round_handler)
            round_handler.close()

    # pylint: disable=too-many-locals,too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def _server_only_round_body(
            self, expected, round_num,
            pri_start_re, pri_finish_re,
            round_dir, log_pos, round_log_path,
    ) -> None:
        """Execute one round of server-only monitoring."""
        logger.info(
            "\n%s", "=" * 60,
        )
        logger.info(
            "  Round %d: expecting %d request(s)",
            round_num, expected,
        )
        logger.info("=" * 60)

        before_server = (
            ResourceMonitor.snapshot(self.server_proc)
            if self.server_proc else None
        )
        if before_server:
            ResourceMonitor.log_snapshot(
                "Server BEFORE", before_server,
            )
        mem = psutil.virtual_memory()
        before_used_mb = (
            (mem.total - mem.available) / (1024 ** 2)
        )
        avail_gb = mem.available / (1024 ** 3)
        total_gb = mem.total / (1024 ** 3)
        logger.info(
            "  System BEFORE: %.0f%% used"
            " (%.0fM used / %.1fG free / %.1fG total)",
            mem.percent, before_used_mb,
            avail_gb, total_gb,
        )
        before_sys_mem_pct = mem.percent
        before_kernel = self._read_kernel_memory()

        logger.info(
            "\nWaiting for %d request(s) in server"
            " log...\n"
            "  Start the client on the remote"
            " machine now.",
            expected,
        )

        count, completed, peak_server, \
            peak_threads, \
            peak_sys_mem_pct, elapsed, interrupted, \
            peak_sys_cpu, avg_sys_cpu = (
                self._tail_server_log(
                    expected, log_pos,
                    pri_start_re, pri_finish_re,
                    before_server, before_sys_mem_pct,
                )
            )

        logger.info(
            "\n  Monitoring complete: %d/%d received,"
            " %d/%d processed in %.1fs",
            count, expected, completed,
            count, elapsed,
        )

        after_server = (
            ResourceMonitor.snapshot(self.server_proc)
            if self.server_proc else None
        )
        after_kernel = self._read_kernel_memory()
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024 ** 3)
        peak_used_mb = (
            peak_sys_mem_pct / 100.0
            * mem.total / (1024 ** 2)
        )
        peak_free_gb = total_gb - peak_used_mb / 1024.0
        logger.info(
            "\n  Peak memory usage: %.0fM / %.1fG"
            " (%.0f%% used, %.1fG free)",
            peak_used_mb, total_gb,
            peak_sys_mem_pct, peak_free_gb,
        )
        ncores = psutil.cpu_count() or 1
        logger.info(
            "  Peak CPU usage: %.0f%% (%.2f of %d cores)",
            peak_sys_cpu,
            peak_sys_cpu / 100.0 * ncores, ncores,
        )

        peak_rss_for_breakdown = 0.0
        if peak_server:
            peak_rss_for_breakdown = (
                peak_server.get("rss", 0)
            )
        elif after_server:
            peak_rss_for_breakdown = (
                after_server.get("rss", 0)
            )
        kernel_breakdown = self._log_kernel_breakdown(
            before_kernel, after_kernel,
            peak_rss_for_breakdown,
            log=False,
        )

        self._export_server_only_json(
            round_dir, expected, count, elapsed,
            before_server, after_server, peak_server,
            peak_threads,
            before_sys_mem_pct, peak_sys_mem_pct,
            mem.percent, interrupted,
            kernel_breakdown,
            avg_sys_cpu=avg_sys_cpu,
            peak_sys_cpu=peak_sys_cpu,
        )

        self._append_server_history_record(
            expected, count, elapsed, peak_server, peak_sys_cpu,
            self._server_only_primary_pairs(log_pos, pri_start_re),
        )

        self._archive_server_log_to(round_dir)

        logger.info("\n%s", "=" * 60)
        logger.info("  OUTPUT FILES")
        logger.info("=" * 60)
        logger.info("  Directory:   %s", round_dir)
        json_path = os.path.join(
            round_dir, "raw_results.json",
        )
        if os.path.isfile(json_path):
            logger.info(
                "  Raw results: %s", json_path,
            )
        gz_path = os.path.join(
            round_dir, "server.log.gz",
        )
        if os.path.isfile(gz_path):
            size_mb = (
                os.path.getsize(gz_path) / (1024 * 1024)
            )
            logger.info(
                "  Server log:  %s (%.1fM)",
                gz_path, size_mb,
            )
        logger.info(
            "  Stdout log:  %s", round_log_path,
        )
        for history_path in (
            self._history_path(),
            self._history_path(successful=False),
        ):
            if os.path.isfile(history_path):
                logger.info("  History:     %s", history_path)

        logger.info(
            "\n%s", "\u2500" * 45,
        )
        logger.info(
            "  Round %d complete. Ready for next"
            " round.", round_num,
        )
        logger.info("%s", "\u2500" * 45)

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _tail_server_log(
            self, expected, log_pos,
            pri_start_re, pri_finish_re,
            before_server, before_sys_mem_pct,
    ):
        """Tail the server log in two phases.

        Phase 1: count Start patterns until all requests
        received.  Phase 2: count Finish patterns until all
        requests processed.

        Returns (count, completed, peak_server,
        peak_threads, peak_sys_mem_pct, elapsed,
        interrupted).
        """
        start_time = time.time()
        count = 0
        completed = 0
        last_heartbeat = start_time
        heartbeat_interval = HEARTBEAT_INTERVAL_SECONDS
        peak_server = before_server
        peak_threads = 0
        peak_sys_mem_pct = before_sys_mem_pct
        peak_sys_cpu = 0.0
        sys_cpu_sum = 0.0
        sys_cpu_n = 0
        interrupted = False
        warned_missing_starts = False
        phase = 1
        log_limit = 5
        # Prime the non-blocking system CPU counter.
        psutil.cpu_percent(interval=None)

        try:
            with open(
                    self.server_log, "r",
                    encoding="utf-8",
            ) as log_fh:
                log_fh.seek(log_pos)
                last_monitor = start_time
                monitor_interval = 1.0
                while True:
                    if phase == 1 and count >= expected:
                        now = time.time()
                        elapsed = now - start_time
                        logger.info(
                            "\n  All %d request(s)"
                            " received (%.1fs)."
                            " Monitoring until"
                            " processing completes"
                            "...",
                            expected, elapsed,
                        )
                        phase = 2
                    if (phase == 2
                            and completed >= count):
                        break
                    # Guard: completions arriving without
                    # matching starts means the monitor was
                    # started after the client fired, so the
                    # Start lines predate our read position and
                    # were skipped. Warn and finish gracefully
                    # instead of hanging with negative in-flight.
                    if completed > count:
                        if not warned_missing_starts:
                            logger.warning(
                                "\n  %d completion(s) seen with"
                                " only %d start(s). The"
                                " server-only monitor was"
                                " likely started after the"
                                " client; Start lines predate"
                                " its read position and were"
                                " missed. Received counts are"
                                " unreliable -- start the"
                                " monitor before the client.",
                                completed, count,
                            )
                            warned_missing_starts = True
                        if completed >= expected:
                            break

                    line = log_fh.readline()
                    if line:
                        if (phase == 1
                                and pri_start_re.search(
                                    line)):
                            count += 1
                            now = time.time()
                            ts = time.strftime(
                                "%H:%M:%S",
                                time.localtime(now),
                            )
                            elapsed = (
                                now - start_time
                            )
                            if (count <= log_limit
                                    or count == expected):
                                logger.info(
                                    "  [server] request"
                                    " %d/%d received"
                                    " [%s] (+%.1fs)",
                                    count, expected,
                                    ts, elapsed,
                                )
                        if pri_finish_re.search(line):
                            completed += 1
                            now = time.time()
                            ts = time.strftime(
                                "%H:%M:%S",
                                time.localtime(now),
                            )
                            elapsed = (
                                now - start_time
                            )
                            total = (
                                count if phase == 2
                                else expected
                            )
                            if (completed <= log_limit
                                    or completed
                                    == total):
                                logger.info(
                                    "  [server] request"
                                    " %d/%d completed"
                                    " [%s] (+%.1fs)",
                                    completed, total,
                                    ts, elapsed,
                                )
                        continue
                    pos = log_fh.tell()
                    log_fh.seek(pos)
                    time.sleep(0.5)

                    now = time.time()
                    elapsed = now - start_time

                    if (now - last_monitor
                            >= monitor_interval):
                        snap = ResourceMonitor.snapshot(
                            self.server_proc,
                        )
                        if snap:
                            if (peak_server is None
                                    or snap.get(
                                        "rss", 0,
                                    ) > peak_server.get(
                                        "rss", 0)):
                                peak_server = snap
                            cur_threads = snap.get(
                                "threads", 0,
                            )
                            if cur_threads > peak_threads:
                                peak_threads = cur_threads
                        cur_mem = (
                            psutil.virtual_memory()
                        )
                        if (cur_mem.percent
                                > peak_sys_mem_pct):
                            peak_sys_mem_pct = (
                                cur_mem.percent
                            )
                        cur_sys_cpu = psutil.cpu_percent(
                            interval=None,
                        )
                        sys_cpu_sum += cur_sys_cpu
                        sys_cpu_n += 1
                        if cur_sys_cpu > peak_sys_cpu:
                            peak_sys_cpu = cur_sys_cpu
                        last_monitor = now

                        if (now - last_heartbeat
                                >= heartbeat_interval):
                            dur_stats = (
                                self._server_only_dur_stats(
                                    log_pos, pri_start_re,
                                )
                            )
                            self._server_only_heartbeat(
                                count, expected,
                                completed,
                                elapsed, now,
                                snap, cur_mem,
                                dur_stats,
                                cur_sys_cpu, peak_sys_cpu,
                            )
                            last_heartbeat = now

                    if (elapsed
                            > self.args.stage_timeout):
                        if phase == 1:
                            logger.warning(
                                "  Stage timeout"
                                " (%.0fs) reached"
                                " with %d/%d"
                                " requests"
                                " received.",
                                self.args.stage_timeout,
                                count, expected,
                            )
                        else:
                            logger.warning(
                                "  Stage timeout"
                                " (%.0fs) reached"
                                " with %d/%d"
                                " requests"
                                " processed.",
                                self.args.stage_timeout,
                                completed, count,
                            )
                        break
        except KeyboardInterrupt:
            interrupted = True
            logger.info(
                "\n  Interrupted \u2014 reporting"
                " partial results...",
            )

        elapsed = time.time() - start_time
        avg_sys_cpu = (
            sys_cpu_sum / sys_cpu_n if sys_cpu_n else 0.0
        )
        return (
            count, completed, peak_server,
            peak_threads,
            peak_sys_mem_pct, elapsed, interrupted,
            peak_sys_cpu, avg_sys_cpu,
        )

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _export_server_only_json(
            self, round_dir, expected, count,
            elapsed, before_server, after_server,
            peak_server, peak_threads,
            before_sys_pct, peak_sys_pct,
            after_sys_pct, interrupted,
            kernel_breakdown=None,
            avg_sys_cpu=None, peak_sys_cpu=None,
    ) -> None:
        """Write raw_results.json for a server-only round."""
        server_cpu_seconds = None
        if before_server and after_server:
            cpu_before = before_server.get("cpu_seconds")
            cpu_after = after_server.get("cpu_seconds")
            if (cpu_before is not None
                    and cpu_after is not None):
                server_cpu_seconds = cpu_after - cpu_before
        raw_data = {
            "test_metadata": {
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%S%z",
                ),
                "hostname": socket.gethostname(),
                "python_version": (
                    platform.python_version()
                ),
                "platform": platform.platform(),
                "mode": "server-only",
                "agent": self.args.agent,
            },
            "round": {
                "expected_requests": expected,
                "received_requests": count,
                "elapsed_seconds": round(elapsed, 2),
                "interrupted": interrupted,
            },
            "server_resources": {
                "before": before_server,
                "after": after_server,
                "peak": peak_server,
                "peak_threads": peak_threads,
            },
            "system_memory": {
                "before_pct": before_sys_pct,
                "peak_pct": peak_sys_pct,
                "after_pct": after_sys_pct,
            },
            "system_cpu": {
                "avg_pct": avg_sys_cpu,
                "peak_pct": peak_sys_cpu,
                "server_cpu_seconds_total": server_cpu_seconds,
                "server_cpu_seconds_per_request": (
                    server_cpu_seconds / count
                    if (server_cpu_seconds is not None
                        and count > 0)
                    else None
                ),
            },
        }
        if kernel_breakdown:
            raw_data["kernel_memory_breakdown"] = (
                kernel_breakdown
            )
        json_path = os.path.join(
            round_dir, "raw_results.json",
        )
        with open(
                json_path, "w", encoding="utf-8",
        ) as fh:
            json.dump(raw_data, fh, indent=2)

    @staticmethod
    def _read_kernel_memory() -> Optional[Dict[str, float]]:
        """Read kernel memory breakdown from /proc/meminfo.

        Returns a dict with values in MB, or None if not on
        Linux.
        """
        if not os.path.isfile("/proc/meminfo"):
            return None
        result = {}
        try:
            with open(
                    "/proc/meminfo", "r", encoding="utf-8",
            ) as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    key = parts[0].rstrip(":")
                    val_kb = int(parts[1])
                    result[key] = val_kb / 1024.0
        except (OSError, ValueError):
            return None

        tcp_mem_mb = 0.0
        try:
            with open(
                    "/proc/net/sockstat", "r",
                    encoding="utf-8",
            ) as fh:
                for line in fh:
                    if line.startswith("TCP:"):
                        parts = line.split()
                        idx = parts.index("mem")
                        pages = int(parts[idx + 1])
                        tcp_mem_mb = (pages * 4) / 1024.0
                        break
        except (OSError, ValueError, IndexError):
            pass
        result["TcpMem"] = tcp_mem_mb
        return result

    @staticmethod
    def _log_kernel_breakdown(
            before_kernel, after_kernel, server_rss_peak,
            *, log=True,
    ) -> Dict[str, float]:
        """Compute the kernel memory breakdown (delta).

        When ``log`` is False the values are still returned for JSON
        export but nothing is printed to the console.
        """
        if not after_kernel:
            return {}

        rss_mb = server_rss_peak or 0.0
        kern_stacks = after_kernel.get(
            "KernelStack", 0,
        )
        page_tables = after_kernel.get(
            "PageTables", 0,
        )
        slab = after_kernel.get("Slab", 0)
        cached = (
            after_kernel.get("Cached", 0)
            + after_kernel.get("Buffers", 0)
        )
        tcp_mem = after_kernel.get("TcpMem", 0)
        mem_total = after_kernel.get("MemTotal", 0)
        mem_free = after_kernel.get("MemFree", 0)
        sys_used = mem_total - mem_free

        accounted = (
            rss_mb + kern_stacks + page_tables
            + slab + cached + tcp_mem
        )
        unaccounted = max(0, sys_used - accounted)

        if log:
            logger.info(
                "\n  Kernel memory breakdown:",
            )
            logger.info(
                "    Server RSS:       %.0fM", rss_mb,
            )
            logger.info(
                "    Kernel stacks:    %.0fM", kern_stacks,
            )
            logger.info(
                "    Page tables:      %.0fM", page_tables,
            )
            logger.info(
                "    Slab cache:       %.0fM", slab,
            )
            logger.info(
                "    Page cache:       %.0fM", cached,
            )
            logger.info(
                "    TCP buffers:      %.0fM", tcp_mem,
            )
            logger.info(
                "    %s", "\u2500" * 30,
            )
            logger.info(
                "    Accounted:        %.0fM", accounted,
            )
            logger.info(
                "    Unaccounted:      %.0fM", unaccounted,
            )
            logger.info(
                "    System total:     %.0fM"
                " (used + cache)",
                sys_used,
            )

        return {
            "server_rss_mb": rss_mb,
            "kernel_stacks_mb": kern_stacks,
            "page_tables_mb": page_tables,
            "slab_mb": slab,
            "page_cache_mb": cached,
            "tcp_buffers_mb": tcp_mem,
            "accounted_mb": accounted,
            "unaccounted_mb": unaccounted,
            "system_total_mb": sys_used,
        }

    def _archive_server_log_to(
            self, target_dir,
    ) -> None:
        """Gzip the server log into the given directory."""
        if not self.server_log or not os.path.isfile(
            self.server_log,
        ):
            return
        gz_path = os.path.join(
            target_dir, "server.log.gz",
        )
        with open(self.server_log, "rb") as f_in, \
                gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

    def run(self) -> int:
        """Execute the full load test workflow."""
        level = self.args.level
        self.args.include_tokens = not self.args.no_tokens
        if self.args.http_client:
            self.args.client_only = True
        split_mode = (
            self.args.client_only or self.args.server_only
        )
        if split_mode:
            level = LEVEL_MIN
            self.args.level = LEVEL_MIN
            self.args.monitor_resources = True
        if self.args.yes and level != LEVEL_ADV:
            if not split_mode:
                logger.error(
                    "--yes is only supported at adv level. "
                    "At %s level, the cost confirmation "
                    "prompt is required.",
                    level,
                )
                raise SystemExit(1)
        if (self.args.client_only
                and self.args.server_only):
            logger.error(
                "--client-only and --server-only are "
                "mutually exclusive.",
            )
            raise SystemExit(1)
        if (self.args.client_only
                and self.args.server_log is not None):
            logger.error(
                "--client-only cannot be used with "
                "--server-log (server log is remote).",
            )
            raise SystemExit(1)
        if (self.args.server_only
                and self.args.server_log is None):
            self.args.server_log = "auto"
        explicit = getattr(self.args, "_explicit", set())
        self._apply_level_defaults(self.args, explicit)
        self._apply_scale(self.args)
        self.input_validator.validate_agent_name()
        EnvironmentValidator.validate_environment()
        stale_log_age = self._validate_server_log()

        stages = self.input_validator.resolve_stages()
        total_cap = self.input_validator.resolve_max_requests(
            stages,
        )

        self._setup_test_log()
        if not self.args.server_only:
            self._preflight_server_check()
            self.probe_result = (
                self.input_validator.confirm_cost(
                    stages, total_cap,
                    runner=self.runner,
                    output_dir=self._output_dir,
                    stale_log_age=stale_log_age,
                )
            )

        is_local = self.args.host in LOCAL_HOSTS
        monitor_resources = (
            level != LEVEL_MIN or self.args.monitor_resources
            or split_mode
        )

        if self.args.client_only:
            if self.args.http_client:
                logger.info(
                    "Client-only mode (HTTP threads): "
                    "skipping server process detection.",
                )
            else:
                logger.info(
                    "Client-only mode: skipping server "
                    "process detection.",
                )
        elif self.args.server_only:
            self.server_proc = (
                EnvironmentValidator.find_local_server(
                    self.args,
                )
            )
        else:
            needs_server_proc = (
                (monitor_resources and is_local
                 and level != LEVEL_MIN)
                or self.args.server_log is not None
            )
            if needs_server_proc and is_local:
                self.server_proc = (
                    EnvironmentValidator.find_local_server(
                        self.args,
                    )
                )
            elif (monitor_resources and is_local
                  and level == LEVEL_MIN):
                if EnvironmentValidator.is_port_open(
                    self.args.host, self.args.port,
                ):
                    self.server_proc = (
                        EnvironmentValidator.find_local_server(
                            self.args,
                        )
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
                logger.info(
                    "  server_log=%s", self.server_log,
                )
            return self._run_server_only_monitor()

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
        pre_test_log_pos = (
            self.log_monitor.read_position()
            if self.server_log else None
        )
        prev_sigint_handler = self._install_interrupt_handler()
        try:
            stage_summaries = self._run_all_stages(
                stages, total_cap,
            )

            if self._aborted:
                exit_code = 1
            if self._interrupted:
                logger.warning(
                    "\n  Test interrupted (Ctrl-C) — the results "
                    "below cover only the requests that completed "
                    "before the interrupt.",
                )

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

            server_chat_timing = []
            if self.server_log and pre_test_log_pos is not None:
                server_chat_timing = (
                    self.log_monitor
                    .parse_streaming_chat_timing_since(
                        pre_test_log_pos,
                    )
                )

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

            if self._interrupted:
                exit_code = 2
            elif not self._aborted:
                exit_code = self._check_results(stage_summaries)
            self._export_raw_json(
                stage_summaries, exit_code=exit_code,
            )
            self._maybe_write_summary(
                stage_summaries, server_chat_timing,
            )
            if self._interrupted:
                self._rename_interrupted()
        except KeyboardInterrupt:
            logger.info(
                "\n  Interrupted — saving partial results...",
            )
            self._export_raw_json(
                stage_summaries, exit_code=2,
            )
            self._rename_interrupted()
            exit_code = 2
        finally:
            if prev_sigint_handler is not None:
                signal.signal(signal.SIGINT, prev_sigint_handler)
            self._append_history_record(stage_summaries)
            self._finalize_test_log(stage_summaries)

        return exit_code

    def was_interrupted(self) -> bool:
        """Return True if the run was stopped early by Ctrl-C."""
        return self._interrupted

    def _install_interrupt_handler(self):
        """Install a SIGINT handler that requests a graceful stop.

        The first Ctrl-C sets a cancel event so in-flight requests are
        killed and the completed ones are still summarized.  A second
        Ctrl-C restores the previous handler so the interpreter exits
        immediately.  Returns the previous handler (or None if it could
        not be installed, e.g. not on the main thread).
        """
        def _handle_sigint(_signum, _frame):
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

    def _history_path(self, *, successful: bool = True) -> str:
        """Return the append-only trend-history JSONL path.

        Successful runs go to ``history.jsonl`` so the trend file stays
        clean for plotting; runs that could not determine the server
        version or completed no requests go to ``history_unknown.jsonl``
        so they are kept for debugging without polluting the trend data.

        Honours ``--history-file`` (the unknown records are written to a
        sibling ``*_unknown`` file) and otherwise defaults to
        ``<output-base>/history[_unknown].jsonl`` so records accumulate
        outside the per-run output directories.
        """
        if self.args.history_file:
            if successful:
                return self.args.history_file
            root, ext = os.path.splitext(self.args.history_file)
            return f"{root}_unknown{ext or '.jsonl'}"
        base = self.args.output_dir or os.path.join(
            tempfile.gettempdir(), "load_test",
        )
        name = (
            HISTORY_FILE_NAME if successful
            else HISTORY_UNKNOWN_FILE_NAME
        )
        return os.path.join(base, name)

    def _append_history_record(self, stage_summaries) -> None:
        """Append one trend record per client run for plotting later.

        Records how many requests completed under each fixed time
        threshold, plus the neuro-san version, so throughput can be
        tracked over time.  Best-effort: any write failure is logged
        and swallowed so it never fails the test.
        """
        results = []
        for summary in stage_summaries:
            results.extend(summary.get("results", []))
        if not results:
            return

        durations = [
            r.get("elapsed", 0.0) for r in results
            if r.get("status") == STATUS_CREATED
        ]
        completed = len(durations)
        avg_duration = (
            round(sum(durations) / completed, 2) if completed else 0.0
        )
        ttfts = [
            r.get("ttft", 0.0) for r in results
            if r.get("status") == STATUS_CREATED
            and r.get("ttft", 0.0) > 0
        ]
        avg_first_response = (
            round(sum(ttfts) / len(ttfts), 2) if ttfts else 0.0
        )
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "neuro_san_version": self._server_ns_version or "unknown",
            "host": self.args.host,
            "agent": self.args.agent,
            "transport": (
                "http" if getattr(self.args, "http_client", False)
                else "subprocess"
            ),
            "total_requests": len(results),
            "completed": completed,
            "avg_first_response_s": avg_first_response,
            "avg_duration_s": avg_duration,
            "wall_time_s": round(
                sum(s.get("elapsed", 0.0) for s in stage_summaries), 2,
            ),
        }
        for threshold in HISTORY_THRESHOLDS_SECONDS:
            record[f"completed_within_{int(threshold)}s"] = sum(
                1 for d in durations if d <= threshold
            )
        successful = (
            completed > 0
            and record.get("neuro_san_version") != "unknown"
        )
        self._write_history_record(record, successful=successful)

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _append_server_history_record(
            self, expected, received, elapsed,
            peak_server, peak_sys_cpu, primary_pairs=None,
    ) -> None:
        """Append one server-only trend record for plotting later.

        Records the server's resource peaks (CPU cores, RSS in GB),
        its neuro-san version, and — derived from the primary agent's
        Start/Finish log pairs — server-side processing durations.
        Keyed with ``mode="server-only"`` so it is distinguishable
        from client records in the same file.

        ``time_to_first_completed_s`` is the server-side time from the
        first request's Start to the first request's Finish; it is not
        the client's per-request time-to-first-response (TTFR), which
        the server log has no way to measure.
        """
        primary_pairs = primary_pairs or []
        durations = [
            float(p["duration"]) for p in primary_pairs
            if isinstance(p.get("duration"), (int, float))
            and p["duration"] > 0
        ]
        avg_duration = (
            round(sum(durations) / len(durations), 2)
            if durations else 0.0
        )
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "neuro_san_version": self._server_ns_version or "unknown",
            "host": self.args.host,
            "agent": self.args.agent,
            "mode": "server-only",
            "expected_requests": expected,
            "received_requests": received,
            "peak_cpu_cores": round(
                (peak_sys_cpu or 0.0) / 100
                * (psutil.cpu_count() or 1), 2,
            ),
            "peak_memory_gb": (
                round(peak_server.get("rss", 0.0) / 1024, 2)
                if peak_server else None
            ),
            "time_to_first_completed_s": self._time_to_first_completed(
                primary_pairs,
            ),
            "avg_duration_s": avg_duration,
            "wall_time_s": round(elapsed, 2),
        }
        for threshold in HISTORY_THRESHOLDS_SECONDS:
            record[f"completed_within_{int(threshold)}s"] = sum(
                1 for d in durations if d <= threshold
            )
        successful = (
            received > 0
            and record.get("neuro_san_version") != "unknown"
        )
        self._write_history_record(record, successful=successful)

    @staticmethod
    def _time_to_first_completed(primary_pairs) -> float:
        """Seconds from the first request's Start to the first Finish.

        Returns 0.0 when no primary request completed.
        """
        starts = [
            p["start_ts"] for p in primary_pairs
            if isinstance(p.get("start_ts"), (int, float))
        ]
        finishes = [
            p["finish_ts"] for p in primary_pairs
            if isinstance(p.get("finish_ts"), (int, float))
        ]
        if not starts or not finishes:
            return 0.0
        return round(min(finishes) - min(starts), 2)

    def _write_history_record(
            self, record, *, successful: bool = True,
    ) -> None:
        """Append one JSON record to the trend-history file.

        ``successful`` selects the destination: clean trend file for
        good runs, ``history_unknown.jsonl`` otherwise.  Best-effort:
        any write failure is logged and swallowed so it never fails the
        run.
        """
        path = self._history_path(successful=successful)
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            logger.info("  Trend history appended: %s", path)
        except OSError as exc:
            logger.warning(
                "  Could not write trend history to %s: %s",
                path, exc,
            )

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
                "neuro_san_version": self._resolve_ns_version(),
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

    def _rename_interrupted(self) -> None:
        """Append _interrupted to the output directory name."""
        if self._output_dir is None:
            return
        new_path = self._output_dir + "_interrupted"
        try:
            os.rename(self._output_dir, new_path)
            self._output_dir = new_path
            logger.info(
                "  Renamed output to: %s", new_path,
            )
        except OSError as exc:
            logger.warning(
                "  Could not rename output dir: %s", exc,
            )

    def _maybe_write_summary(
            self, stage_summaries, server_chat_timing,
    ) -> None:
        """Write summary.txt for adv level only.

        With --yes: auto-write.  Without --yes: prompt the user.
        """
        if self.args.level != LEVEL_ADV:
            return
        if not getattr(self.args, "yes", False):
            try:
                answer = input(
                    "\nSave summary.txt? [y/N] ",
                )
            except (EOFError, KeyboardInterrupt):
                return
            if answer.strip().lower() != "y":
                return
        writer = SummaryFileWriter(
            stage_summaries, self.args,
            server_chat_timing=server_chat_timing,
        )
        writer.write(self._output_dir)

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

    def _host_tag(self) -> str:
        """Return the ``--host`` value as a folder-name segment."""
        return re.sub(r"[^0-9A-Za-z.+-]", "-", str(self.args.host))

    def _resolve_ns_version(self) -> Optional[str]:
        """Return the neuro-san version to tag this run with.

        Prefers the *server's* version (via ``/healthz``) so the tag
        reflects what is actually being exercised, even when the client
        runs from a different checkout/venv or a remote machine.  The
        result is cached in ``_server_ns_version``.  Falls back to the
        locally installed package version when the server is
        unreachable or does not report one.
        """
        if not self._server_ns_version:
            self._server_ns_version = self._fetch_server_version()
        return (
            self._server_ns_version
            or self._get_package_version("neuro-san")
        )

    def _version_tag(self) -> str:
        """Return a folder-name segment for the neuro-san version.

        E.g. ``ns0.6.81`` from the server's ``/healthz`` version, or
        ``""`` when the version can't be determined.
        """
        version = self._resolve_ns_version()
        if not version:
            return ""
        safe = re.sub(r"[^0-9A-Za-z.+-]", "-", version)
        return f"ns{safe}"

    def _run_folder_name(self, timestamp, count) -> str:
        """Build ``<timestamp>_<host>[_ns<version>]_<count>``."""
        parts = [timestamp, self._host_tag()]
        vtag = self._version_tag()
        if vtag:
            parts.append(vtag)
        parts.append(str(count))
        return "_".join(parts)

    @staticmethod
    def main() -> None:
        """Entry point for the load test script."""
        args = LoadTestOrchestrator.parse_args()
        if args.rebuild:
            ResultsRebuilder(
                args.rebuild,
                force=args.rebuild_all,
            ).run()
            return
        if args.compare:
            agent_filter = None
            if args.compare_agent:
                agent_filter = [
                    a.strip()
                    for a in args.compare_agent.split(",")
                ]
            run_filter = None
            if args.compare_runs:
                run_filter = [
                    r.strip()
                    for r in args.compare_runs.split(",")
                ]
            CrossRunComparison(
                args.compare,
                agent_filter=agent_filter,
                baseline_requests=args.compare_baseline,
                run_filter=run_filter,
            ).run()
            return
        orchestrator = LoadTestOrchestrator(args)
        exit_code = orchestrator.run()
        if orchestrator.was_interrupted():
            # After Ctrl-C some worker threads (e.g. un-killable
            # in-thread HTTP requests) may still be blocked.  Results
            # are already printed and saved, so exit hard rather than
            # hang joining those threads at interpreter shutdown.
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(exit_code)  # pylint: disable=protected-access
        sys.exit(exit_code)


if __name__ == "__main__":
    LoadTestOrchestrator.main()
