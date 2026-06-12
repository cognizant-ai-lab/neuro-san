#!/usr/bin/env python
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
from tests.load_tests.monitoring.resource_monitor import snapshot
from tests.load_tests.monitoring.resource_monitor import log_snapshot
from tests.load_tests.monitoring.server_log_monitor import read_log_position
from tests.load_tests.monitoring.server_log_monitor import count_retries_since
from tests.load_tests.monitoring.server_log_monitor import count_requests_since
from tests.load_tests.monitoring.server_log_monitor import parse_token_accounting_since
from tests.load_tests.monitoring.server_log_monitor import scan_disconnections_since
from tests.load_tests.monitoring.server_log_monitor import start_log_monitor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.reporting.csv_export import append_resource_history
from tests.load_tests.reporting.csv_export import export_per_request_csv
from tests.load_tests.reporting.csv_export import export_summary_csv
from tests.load_tests.reporting.disconnection_report import log_disconnection_summary
from tests.load_tests.reporting.pool_analysis import log_pool_reuse_analysis
from tests.load_tests.reporting.recommendations import log_recommendations
from tests.load_tests.reporting.resource_report import build_client_row
from tests.load_tests.reporting.resource_report import build_resource_row
from tests.load_tests.reporting.resource_report import log_client_analysis
from tests.load_tests.reporting.resource_report import log_resource_analysis
from tests.load_tests.reporting.summary import log_overall_results
from tests.load_tests.reporting.summary import log_ramp_summary
from tests.load_tests.traffic.runner import count_results
from tests.load_tests.traffic.runner import log_token_summary
from tests.load_tests.traffic.runner import run_stage
from tests.load_tests.validation.environment import find_local_server
from tests.load_tests.validation.environment import validate_environment
from tests.load_tests.validation.input_validation import confirm_cost
from tests.load_tests.validation.input_validation import resolve_max_requests
from tests.load_tests.validation.input_validation import resolve_stages
from tests.load_tests.validation.output_validation import log_disconnections
from tests.load_tests.validation.output_validation import log_retry_activity
from tests.load_tests.validation.output_validation import log_server_validation
from tests.load_tests.validation.output_validation import log_stage_results

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments for the load test."""
    parser = argparse.ArgumentParser(
        description="Load-test neuro-san agent networks with real LLM calls.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Agent selection
    parser.add_argument(
        "--agent",
        type=str,
        default="hello_world",
        help="Agent network name to test (default: hello_world). "
             "Must be registered in the server's AGENT_REGISTRY_PATH.",
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
        help="Path to the project root where the server is running from "
             "(e.g., /path/to/neuro-san-studio). Used to find agent "
             "profiles at {project-root}/tests/load_tests/profiles/. "
             "Falls back to PYTHONPATH if not set.",
    )

    # Flat mode arguments
    parser.add_argument(
        "--num-requests",
        type=int,
        default=3,
        help="Number of requests per round in flat mode (default: 3). "
             "Ignored when --ramp is used.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=3,
        help="Max concurrent workers in flat mode (default: 3). "
             "Ignored when --ramp is used.",
    )
    parser.add_argument(
        "--num-rounds",
        type=int,
        default=1,
        help="Number of rounds in flat mode, or number of times to "
             "repeat the full ramp sequence (default: 1).",
    )

    # Ramp mode arguments
    parser.add_argument(
        "--ramp",
        action="store_true",
        default=False,
        help="Enable staged ramp-up mode. Runs escalating concurrency "
             "stages instead of flat requests.",
    )
    parser.add_argument(
        "--stages",
        type=str,
        default=None,
        help="Comma-separated concurrency levels for ramp-up mode "
             "(default: 10,30,50,100). Only used with --ramp.",
    )

    # Common arguments
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="Hard cap on total requests across all stages/rounds. "
             "Cost safeguard for real LLM calls. "
             "Default: 100 for flat mode, sum of stages for ramp mode.",
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
        help="Hard timeout per request in seconds (default: 1200). "
             "Safety net to prevent requests from running forever.",
    )
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=DEFAULT_IDLE_TIMEOUT_SECONDS,
        help="Kill a request if no output for this many seconds "
             "(default: 900). Detects hanging requests.",
    )
    parser.add_argument(
        "--settle-time",
        type=int,
        default=15,
        help="Seconds to wait after each stage for cleanup (default: 15)",
    )
    parser.add_argument(
        "--same-prompt",
        action="store_true",
        default=False,
        help="Use the same prompt for all requests (collision stress test). "
             "Default is varied prompts from the agent's prompt pool.",
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
        help="Explicit path to neuro-san server log file for retry "
             "monitoring. Overrides auto-detection.",
    )
    parser.add_argument(
        "--level",
        type=str,
        choices=[LEVEL_MIN, LEVEL_NORM, LEVEL_ADV],
        default=LEVEL_NORM,
        help="Test depth level (default: norm). "
             "min: traffic + validation only. "
             "norm: adds server log and resource monitoring. "
             "adv: adds tokens, CSV, recommendations, pool analysis.",
    )
    parser.add_argument(
        "--skip-reservation-check",
        action="store_true",
        default=False,
        help="Skip reservation_id validation. A request is marked "
             "CREATED if other success fields are present, even without "
             "a reservation_id.",
    )
    return parser.parse_args()


def _attach_token_data(results, token_data):
    """Attach token accounting data to request results.

    The server assigns its own request_id numbering (e.g. request-3,
    request-4) which differs from the client's (request-1, request-2).
    Match by order: sort server entries by request_id number, then
    attach to client results in submission order.
    """
    if not token_data:
        return

    def _sort_key(rid):
        match = re.search(r"(\d+)$", rid)
        return int(match.group(1)) if match else 0

    sorted_entries = sorted(token_data.values(), key=lambda e: _sort_key(e["request_id"]))
    sorted_results = sorted(results, key=lambda r: _sort_key(r.get("request_id", "")))

    for result, entry in zip(sorted_results, sorted_entries):
        result["total_tokens"] = entry["total_tokens"]
        result["prompt_tokens"] = entry["prompt_tokens"]
        result["completion_tokens"] = entry["completion_tokens"]
        result["llm_calls"] = entry["llm_calls"]
        result["model"] = entry["model"]


class LoadTestOrchestrator:
    """Orchestrates the full load test workflow."""

    def __init__(self, args):
        """Initialize the orchestrator with parsed arguments."""
        self.args = args
        self.profile = AgentProfile.load(
            args.agent, args.profile, args.project_root,
        )
        self.server_proc = None
        self.server_log = args.server_log
        self._output_dir = None
        self._test_log_path = None
        self._test_log_handler = None

    # pylint: disable=too-many-locals,too-many-statements,too-many-branches
    def _run_all_stages(self, stages, total_cap):
        """Execute all stages of the load test, collecting data per stage."""
        level = self.args.level
        monitor_resources = level != LEVEL_MIN
        parse_tokens = level == LEVEL_ADV

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

                logger.info("\n%s", "=" * 60)
                stage_label = f"[STAGE {stage_num}] {actual_requests} concurrent connections"
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
                    read_log_position(self.server_log)
                    if monitor_resources else None
                )

                before_server = None
                before_client = None
                if monitor_resources:
                    before_server = (
                        snapshot(self.server_proc)
                        if self.server_proc else None
                    )
                    if before_server:
                        log_snapshot("Server BEFORE", before_server)

                    client_proc = psutil.Process()
                    before_client = snapshot(client_proc)
                    if before_client:
                        logger.info(
                            "  Client BEFORE: RSS %.1fM, CPU %.1f%%",
                            before_client["rss"], before_client["cpu"],
                        )

                fire_time = time.time()
                fire_ts = time.strftime("%H:%M:%S", time.localtime(fire_time))
                fire_threads = ""
                if monitor_resources and self.server_proc:
                    try:
                        fire_threads = (
                            f"  threads: {self.server_proc.num_threads()}"
                        )
                    except Exception:  # pylint: disable=broad-exception-caught
                        pass
                logger.info(
                    "\nFiring %s concurrent %s requests... [%s]%s",
                    actual_requests, self.args.agent, fire_ts, fire_threads,
                )

                stop_event = None
                monitor = None
                peak_result = None
                if monitor_resources:
                    stop_event, monitor, peak_result = start_log_monitor(
                        self.server_log, log_pos, actual_requests,
                        fire_time, client_proc,
                        self.profile.primary_start_pattern,
                    )

                elapsed, results, peak_threads = run_stage(
                    self.args, self.profile,
                    actual_requests, actual_requests, global_offset,
                    self.server_proc, self._output_dir,
                )
                if stop_event:
                    stop_event.set()
                if monitor:
                    monitor.join(timeout=2)

                peak_client = None
                settled_client = None
                if monitor_resources:
                    peak_client = peak_result if peak_result else None
                    settled_client = snapshot(client_proc)
                    if before_client and settled_client:
                        rss_before = before_client["rss"]
                        rss_settled = settled_client["rss"]
                        rss_delta = rss_settled - rss_before
                        logger.info(
                            "  Client SETTLED: RSS %.1fM (%+.1fM from before)",
                            rss_settled, rss_delta,
                        )

                global_offset += actual_requests
                total_sent += actual_requests

                counts = count_results(results)

                retries: Dict[str, int] = {}
                total_retries = 0
                amplification = 1.0
                if monitor_resources:
                    retries = count_retries_since(self.server_log, log_pos)
                    total_retries = sum(retries.values())
                    amplification = (
                        (actual_requests + total_retries) / actual_requests
                        if actual_requests > 0 else 1.0
                    )

                log_stage_results(
                    actual_requests, counts, elapsed,
                    self.args.timeout, self.args.idle_timeout,
                    self.args.skip_reservation_check,
                )

                if monitor_resources and self.server_log:
                    log_retry_activity(retries, total_retries, actual_requests)

                server_counts: Dict[str, Any] = {}
                disconnections: List = []
                if monitor_resources:
                    logger.info(
                        "\n  Waiting %ss for server cleanup...",
                        self.args.settle_time,
                    )
                    time.sleep(self.args.settle_time)

                    after_server = (
                        snapshot(self.server_proc)
                        if self.server_proc else None
                    )
                    if after_server:
                        log_snapshot("Server SETTLED", after_server)

                    server_counts = count_requests_since(
                        self.server_log, log_pos,
                        self.profile.primary_start_pattern,
                        self.profile.primary_finish_pattern,
                    )
                    disconnections = scan_disconnections_since(
                        self.server_log, log_pos,
                    )

                    if parse_tokens:
                        token_data = parse_token_accounting_since(
                            self.server_log, log_pos,
                        )
                        _attach_token_data(results, token_data)
                        if token_data:
                            logger.info("\n  Token usage (from server log):")
                            log_token_summary(results)

                    log_disconnections(disconnections)
                    log_server_validation(
                        server_counts, actual_requests, self.args.agent,
                    )

                    if before_server and after_server:
                        resource_rows.append(
                            build_resource_row(
                                f"{actual_requests}",
                                before_server, after_server,
                            ),
                        )

                    if before_client and settled_client:
                        client_resource_rows.append(
                            build_client_row(
                                f"{actual_requests}",
                                before_client, peak_client, settled_client,
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
                    summary_entry["peak_threads"] = peak_threads["peak"]
                stage_summaries.append(summary_entry)

        return stage_summaries, resource_rows, client_resource_rows

    def _setup_test_log(self):
        """Create output directory and add a file handler for logging."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self._output_dir = f"/tmp/load_test/{self.args.level}/{timestamp}"
        os.makedirs(self._output_dir, exist_ok=True)
        self._test_log_path = os.path.join(self._output_dir, "load_test.log")
        self._test_log_handler = logging.FileHandler(
            self._test_log_path, encoding="utf-8",
        )
        self._test_log_handler.setLevel(logging.INFO)
        self._test_log_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(self._test_log_handler)

    def _finalize_test_log(self, stage_summaries):
        """Close the log handler and report the output directory."""
        if self._test_log_handler is not None:
            logger.removeHandler(self._test_log_handler)
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
        """Validate --server-log requirement and path at norm/adv levels."""
        level = self.args.level
        if level == LEVEL_MIN:
            return

        if not self.args.server_log:
            logger.error(
                "--server-log is required at %s level.\n"
                "  Pass the path to your active server log. Example:\n"
                "    --server-log logs/server.log\n\n"
                "  If you started the server with:\n"
                "    python -m neuro_san.service.main_loop"
                ".server_main_loop 2>&1 | tee logs/server.log\n"
                "  then use that same path.",
                level,
            )
            sys.exit(1)

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
        validate_environment()
        self._validate_server_log()

        stages = resolve_stages(self.args)
        total_cap = resolve_max_requests(self.args, stages)

        confirm_cost(self.args, stages, total_cap, self.profile)
        self._setup_test_log()

        is_local = self.args.host in LOCAL_HOSTS

        if level != LEVEL_MIN and is_local:
            self.server_proc, self.server_log = find_local_server(self.args)
        elif level == LEVEL_MIN and is_local:
            logger.info(
                "Level 'min': server monitoring and log reading disabled",
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
        if level != LEVEL_MIN:
            logger.info("  settle_time=%ss", self.args.settle_time)
        if self.server_log:
            logger.info("  server_log=%s", self.server_log)
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
                log_ramp_summary(stage_summaries)

            log_overall_results(stage_summaries, level)

            if level != LEVEL_MIN:
                total_client_reqs = sum(
                    s["concurrent"] for s in stage_summaries
                )
                total_server_calls = sum(
                    s.get("total_started") or 0 for s in stage_summaries
                )

                log_resource_analysis(
                    resource_rows, total_client_reqs, total_server_calls,
                )
                log_disconnection_summary(stage_summaries)
                log_client_analysis(client_rows, total_client_reqs)

            if level == LEVEL_ADV:
                log_pool_reuse_analysis(stage_summaries)
                log_recommendations(
                    stage_summaries, self.args, self._output_dir,
                )
                append_resource_history(
                    stage_summaries, resource_rows, client_rows,
                )
                export_per_request_csv(
                    self._output_dir, stage_summaries, self.args.agent,
                )
                export_summary_csv(
                    self._output_dir, stage_summaries, self.args.agent,
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


def main():
    """Entry point for the load test script."""
    args = parse_args()
    orchestrator = LoadTestOrchestrator(args)
    sys.exit(orchestrator.run())


if __name__ == "__main__":
    main()
