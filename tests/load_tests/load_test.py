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

"""
Generic load-test script for neuro-san agent networks using real LLM calls.

Fires concurrent requests via agent_cli subprocesses, monitors the neuro-san
server for resource usage and max_attempts retry behavior, and prints a
per-stage summary with an overall ramp-up analysis.

Works with any agent network (hello_world, agent_network_designer, music_nerd_pro, etc.)
by loading agent-specific prompts and success criteria from a profile JSON file.

Prerequisites:
    1. neuro-san server running (Terminal 1):
       export AGENT_REGISTRY_PATH=/path/to/registries
       export OPENAI_API_KEY=<your-key>
       python -m neuro_san.service.main_loop.server_main_loop

    2. OPENAI_API_KEY must be set (real LLM calls = real API costs).

Test levels (--level):
    min:  Traffic + validation only. Fast smoke test.
    norm: Adds server log reading and resource monitoring. (default)
    adv:  Adds token parsing, CSV export, recommendations, pool analysis.

Usage examples:
    # Quick smoke test (min level)
    python -m tests.load_tests.load_test --agent hello_world --level min --yes

    # Standard load test with resource monitoring (default: norm)
    python -m tests.load_tests.load_test --agent hello_world --yes

    # Full analysis with CSV and recommendations (adv level)
    python -m tests.load_tests.load_test --agent hello_world --level adv --ramp --yes

    # Custom stages and profile
    python -m tests.load_tests.load_test --agent my_agent --level adv --ramp \\
        --stages 5,10,25 --profile ./my_profile.json --yes

    # Same prompt for all requests (collision stress test)
    python -m tests.load_tests.load_test --agent hello_world --ramp --same-prompt --yes
"""

import argparse
import logging
import os
import re
import sys
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

import psutil

from tests.load_tests.config import DEFAULT_IDLE_TIMEOUT_SECONDS
from tests.load_tests.config import DEFAULT_TIMEOUT_SECONDS
from tests.load_tests.config import LEVEL_ADV
from tests.load_tests.config import LEVEL_MIN
from tests.load_tests.config import LEVEL_NORM
from tests.load_tests.config import LOCAL_HOSTS
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.reporting.csv_export import CsvExporter
from tests.load_tests.reporting.disconnection_report import DisconnectionReporter
from tests.load_tests.reporting.pool_analysis import PoolAnalyzer
from tests.load_tests.reporting.recommendations import RecommendationEngine
from tests.load_tests.reporting.resource_report import ResourceReporter
from tests.load_tests.reporting.summary import SummaryReporter
from tests.load_tests.traffic.runner import TrafficRunner
from tests.load_tests.validation.environment import EnvironmentValidator
from tests.load_tests.validation.input_validation import InputValidator
from tests.load_tests.validation.output_validation import OutputValidator

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class LoadTestOrchestrator:  # pylint: disable=too-many-instance-attributes
    """Orchestrates the full load test workflow."""

    @staticmethod
    def parse_args():
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
            "--profile",
            type=str,
            default=None,
            help="Path to agent profile JSON file. If not set, "
                 "auto-discovers from profiles/ directory.",
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
            help="Max concurrent workers in flat mode (default: 3)."
                 " Ignored when --ramp is used.",
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
                 " Default: 100 for flat mode, sum(stages) * "
                 "num_rounds for ramp mode.",
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
            "--timeout",
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
            help="Skip the cost confirmation prompt",
        )
        parser.add_argument(
            "--server-log",
            type=str,
            default=None,
            help="Explicit path to neuro-san server log file for "
                 "retry monitoring. Overrides auto-detection.",
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
                 "adv: adds token accounting, CSV export, "
                 "recommendations, pool analysis.",
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
            "--include-tokens",
            action="store_true",
            default=False,
            help="Pass --tokens to agent_cli to capture per-request "
                 "token accounting from stdout. Automatically "
                 "enabled at adv level.",
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
        return parser.parse_args()

    @staticmethod
    def _token_sort_key(rid):
        """Extract numeric suffix from a request_id for sorting."""
        match = re.search(r"(\d+)$", rid)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _attach_token_data(results, token_data):
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
            result["total_tokens"] = entry.get("total_tokens")
            result["prompt_tokens"] = entry.get("prompt_tokens")
            result["completion_tokens"] = entry.get(
                "completion_tokens",
            )
            result["llm_calls"] = entry.get("llm_calls")
            result["model"] = entry.get("model")

    def __init__(self, args):
        """Initialize the orchestrator with parsed arguments."""
        self.args = args
        self.profile = AgentProfile.load(
            args.agent, args.profile, args.project_root,
        )
        self.server_proc = None
        self.server_log = args.server_log
        self.probe_result = None
        self._output_dir = None
        self._test_log_path = None
        self._test_log_handler = None

    # pylint: disable=too-many-locals,too-many-statements,too-many-branches
    def _run_all_stages(self, stages, total_cap):
        """Execute all stages of the load test, collecting data per stage."""
        level = self.args.level
        monitor_resources = (
            level != LEVEL_MIN or self.args.monitor_resources
        )
        has_server_log = self.server_log is not None
        parse_tokens = (
            level != LEVEL_MIN or self.args.include_tokens
        )
        probe_result = self.probe_result

        stage_summaries: List[Dict[str, Any]] = []
        resource_rows: List[Tuple] = []
        client_resource_rows: List[Tuple] = []
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
                    return stage_summaries, resource_rows, client_resource_rows

                remaining = total_cap - total_sent
                actual_requests = min(num_concurrent, remaining)
                stage_num = stage_idx + 1
                stage_workers = (
                    self.args.max_workers
                    if not self.args.ramp
                    else actual_requests
                )

                logger.info("\n%s", "=" * 60)
                stage_label = f"[STAGE {stage_num}] {stage_workers} concurrent connections"
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
                    ServerLogMonitor.read_log_position(
                        self.server_log,
                    )
                    if has_server_log else None
                )

                before_server = None
                before_client = None
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
                            before_client.get("rss"), before_client.get("cpu"),
                        )

                fire_time = time.time()
                fire_ts = time.strftime("%H:%M:%S", time.localtime(fire_time))
                fire_threads = ""
                if monitor_resources and self.server_proc:
                    try:
                        fire_threads = (
                            f"  threads: {self.server_proc.num_threads()}"
                        )
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                fire_label = actual_requests
                if probe_result is not None:
                    fire_label = f"{actual_requests} ({actual_requests - 1} + 1 probe)"
                logger.info(
                    "\nFiring %s concurrent %s requests... [%s]%s",
                    fire_label, self.args.agent, fire_ts, fire_threads,
                )

                stop_event = None
                monitor = None
                peak_result = None
                if has_server_log:
                    stop_event, monitor, peak_result = (
                        ServerLogMonitor.start_log_monitor(
                            self.server_log, log_pos,
                            actual_requests,
                            fire_time, client_proc,
                            self.profile.primary_start_pattern,
                        )
                    )

                # If a dry-run probe ran, inject it into stage 1
                stage_requests = actual_requests
                if probe_result is not None:
                    stage_requests = max(actual_requests - 1, 0)

                elapsed, results, peak_threads = TrafficRunner.run_stage(
                    self.args, self.profile,
                    stage_requests, stage_workers,
                    global_offset + (1 if probe_result else 0),
                    self.server_proc, self._output_dir,
                )

                if probe_result is not None:
                    results.insert(0, probe_result)
                    probe_result = None

                if stop_event:
                    stop_event.set()
                if monitor:
                    monitor.join(timeout=2)

                peak_client = None
                settled_client = None
                if monitor_resources:
                    peak_client = peak_result if peak_result else None
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

                global_offset += actual_requests
                total_sent += actual_requests

                counts = OutputValidator.count_results(results)

                retries: Dict[str, int] = {}
                total_retries = 0
                amplification = 1.0
                if has_server_log:
                    retries = ServerLogMonitor.count_retries_since(
                        self.server_log, log_pos,
                    )
                    total_retries = sum(retries.values())
                    amplification = (
                        (actual_requests + total_retries) / actual_requests
                        if actual_requests > 0 else 1.0
                    )

                OutputValidator.log_stage_results(
                    actual_requests, counts, elapsed,
                    self.args.timeout, self.args.idle_timeout,
                    self.args.skip_reservation_check,
                )

                if has_server_log:
                    OutputValidator.log_retry_activity(
                        retries, total_retries, actual_requests,
                    )
                elif monitor_resources:
                    logger.info(
                        "\n  Retry activity: not available "
                        "(no --server-log)",
                    )

                server_counts: Dict[str, Any] = {}
                disconnections: List = []
                network_tokens: List = []
                if monitor_resources or has_server_log:
                    logger.info(
                        "\n  Waiting %ss for server cleanup...",
                        self.args.settle_time,
                    )
                    time.sleep(self.args.settle_time)

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
                            has_server_log, parse_tokens,
                            log_pos, results, actual_requests,
                        )
                    )

                    if before_server and after_server:
                        resource_rows.append(
                            ResourceReporter.build_resource_row(
                                f"{actual_requests}",
                                before_server, after_server,
                            ),
                        )

                    if before_client and settled_client:
                        client_resource_rows.append(
                            ResourceReporter.build_client_row(
                                f"{actual_requests}",
                                before_client,
                                peak_client,
                                settled_client,
                            ),
                        )

                summary_entry = {
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
                    "has_tokens": parse_tokens,
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
                if peak_threads.get("peak") is not None:
                    summary_entry["peak_threads"] = peak_threads.get("peak")
                stage_summaries.append(summary_entry)

        return stage_summaries, resource_rows, client_resource_rows

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _analyze_server_log(
            self, has_server_log, parse_tokens,
            log_pos, results, actual_requests,
    ):
        """Analyze server log or report unavailability.

        Returns (server_counts, disconnections, network_tokens).
        """
        server_counts: Dict[str, Any] = {}
        disconnections: List = []
        network_tokens: List = []
        if has_server_log:
            server_counts = (
                ServerLogMonitor.count_requests_since(
                    self.server_log, log_pos,
                    self.profile.primary_start_pattern,
                    self.profile.primary_finish_pattern,
                )
            )
            disconnections = (
                ServerLogMonitor.scan_disconnections_since(
                    self.server_log, log_pos,
                )
            )
            if parse_tokens:
                token_data = (
                    ServerLogMonitor.parse_token_accounting_since(
                        self.server_log, log_pos,
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
                    ServerLogMonitor.parse_per_network_tokens_since(
                        self.server_log, log_pos,
                    )
                )
            OutputValidator.log_disconnections(disconnections)
            OutputValidator.log_server_validation(
                server_counts, actual_requests,
                self.args.agent,
            )
        else:
            if parse_tokens:
                has_token_data = any(
                    r.get("total_tokens") for r in results
                )
                if has_token_data:
                    logger.info(
                        "\n  Token usage "
                        "(from agent_cli --tokens):",
                    )
                    TrafficRunner.log_token_summary(results)
            logger.info(
                "\n  Server-side validation: "
                "not available (no --server-log)",
            )
        return server_counts, disconnections, network_tokens

    def _setup_test_log(self):
        """Create output directory and add a file handler for logging."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base = self.args.output_dir or "/tmp/load_test"
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

    def _finalize_test_log(self, stage_summaries):
        """Close the log handler and report the output directory."""
        if self._test_log_handler is not None:
            logging.getLogger().removeHandler(self._test_log_handler)
            self._test_log_handler.close()
        if self._output_dir is None:
            return
        has_failures = any(
            summary.get("counts", {}).get("FAILED", 0) > 0
            or summary.get("counts", {}).get("TIMEOUT", 0) > 0
            or summary.get("counts", {}).get("KILLED", 0) > 0
            for summary in stage_summaries
        )
        if has_failures:
            logger.info("\nOutput (with failures): %s", self._output_dir)
        else:
            logger.info("\nOutput: %s", self._output_dir)

    def _validate_server_log(self):
        """Validate --server-log path when provided.

        At norm/adv levels without --server-log, logs a warning listing
        which features will be unavailable.
        """
        level = self.args.level
        if level == LEVEL_MIN and not self.args.server_log:
            return

        if not self.args.server_log:
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
                "    --server-log logs/server.log",
                level,
            )
            return

        if not os.path.isfile(self.args.server_log):
            logger.error(
                "Server log not found: %s",
                self.args.server_log,
            )
            sys.exit(1)

        mtime = os.path.getmtime(self.args.server_log)
        age_seconds = time.time() - mtime
        if age_seconds > 300:
            age_min = int(age_seconds // 60)
            logger.warning(
                "WARNING: Server log appears stale "
                "(last modified %sm ago): %s\n"
                "         Make sure this is the active server log.",
                age_min, self.args.server_log,
            )

    def run(self):
        """Execute the full load test workflow."""
        level = self.args.level
        EnvironmentValidator.validate_environment()
        self._validate_server_log()

        stages = InputValidator.resolve_stages(self.args)
        total_cap = InputValidator.resolve_max_requests(
            self.args, stages,
        )

        self._setup_test_log()
        self.probe_result = InputValidator.confirm_cost(
            self.args, stages, total_cap, self.profile,
            self._output_dir,
        )

        is_local = self.args.host in LOCAL_HOSTS
        monitor_resources = (
            level != LEVEL_MIN or self.args.monitor_resources
        )

        if monitor_resources and is_local:
            self.server_proc, self.server_log = (
                EnvironmentValidator.find_local_server(self.args)
            )
        elif level == LEVEL_MIN and not self.args.monitor_resources:
            logger.info(
                "Level 'min': resource monitoring disabled. "
                "Use --monitor-resources to enable.",
            )
        else:
            logger.info(
                "Remote mode: targeting %s:%s",
                self.args.host, self.args.port,
            )
            logger.info("  Process monitoring disabled (server is not local)")

        prompt_mode = "same" if self.args.same_prompt else "varied"
        mode = "ramp" if self.args.ramp else "flat"
        logger.info(
            "\nConfig: agent=%s, mode=%s, level=%s, "
            "stages=%s, rounds=%s, max_requests=%s, host=%s, port=%s, "
            "timeout=%ss, idle_timeout=%ss, prompt_mode=%s",
            self.args.agent, mode, level, stages,
            self.args.num_rounds, total_cap,
            self.args.host, self.args.port, self.args.timeout,
            self.args.idle_timeout, prompt_mode,
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

        stage_summaries: List[Dict[str, Any]] = []
        exit_code = 1
        try:
            stage_summaries, resource_rows, client_rows = self._run_all_stages(
                stages, total_cap,
            )

            if len(stage_summaries) > 1:
                SummaryReporter.log_ramp_summary(stage_summaries)

            SummaryReporter.log_overall_results(
                stage_summaries, level,
            )

            if monitor_resources:
                total_client_reqs = sum(
                    s.get("concurrent", 0) for s in stage_summaries
                )
                total_server_calls = sum(
                    s.get("total_started") or 0 for s in stage_summaries
                )

                ResourceReporter.log_resource_analysis(
                    resource_rows, total_client_reqs,
                    total_server_calls,
                )
                DisconnectionReporter.log_disconnection_summary(
                    stage_summaries,
                )
                ResourceReporter.log_client_analysis(
                    client_rows, total_client_reqs,
                )

            if level == LEVEL_ADV:
                has_server_log = self.server_log is not None
                if has_server_log:
                    PoolAnalyzer.log_pool_reuse_analysis(
                        stage_summaries,
                    )
                else:
                    logger.info(
                        "\n  Pool reuse analysis: "
                        "not available (no --server-log)",
                    )
                RecommendationEngine.log_recommendations(
                    stage_summaries, self.args,
                    self._output_dir,
                )
                CsvExporter.export_resources_csv(
                    self._output_dir, stage_summaries,
                    resource_rows, client_rows, self.args,
                )
                CsvExporter.export_per_request_csv(
                    self._output_dir, stage_summaries,
                    self.args.agent,
                )
                CsvExporter.export_per_network_csv(
                    self._output_dir, stage_summaries,
                    self.args.agent,
                )

            exit_code = self._check_results(stage_summaries)
        finally:
            self._finalize_test_log(stage_summaries)

        return exit_code

    def _check_results(self, stage_summaries):
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
    def main():
        """Entry point for the load test script."""
        args = LoadTestOrchestrator.parse_args()
        orchestrator = LoadTestOrchestrator(args)
        sys.exit(orchestrator.run())


if __name__ == "__main__":
    LoadTestOrchestrator.main()
