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

"""Validation — environment, input, and output validation for load tests."""

import logging
import os
import socket
import sys
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import psutil

from tests.load_tests.config import DEFAULT_STAGES
from tests.load_tests.config import RETRY_ERROR_TYPES
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.traffic.runner import TrafficRunner

logger = logging.getLogger(__name__)


class EnvironmentValidator:
    """Validates the runtime environment for load testing."""

    @staticmethod
    def validate_environment():
        """Validate that OPENAI_API_KEY is set and no mock LLM is active."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key is None or len(api_key) == 0:
            logger.error(
                "OPENAI_API_KEY is not set.\n"
                "This test requires real LLM calls. Set your API key:\n"
                "  export OPENAI_API_KEY=<your-key>"
            )
            sys.exit(1)
        logger.info("OPENAI_API_KEY is set.")
        EnvironmentValidator._check_no_mock_environment()

    @staticmethod
    def _check_no_mock_environment():
        """Exit if a mock LLM environment is detected."""
        issues = []
        api_base = os.environ.get("OPENAI_API_BASE")
        if api_base:
            issues.append(f"  OPENAI_API_BASE={api_base}")
        mock_proc = ResourceMonitor.find_process("mock_llm_server")
        if mock_proc is not None:
            issues.append(
                f"  mock_llm_server process running "
                f"(PID {mock_proc.pid})"
            )
        if issues:
            logger.error(
                "Mock LLM environment detected — this test requires "
                "real LLM calls.\n%s\n\n"
                "Unset OPENAI_API_BASE and stop the mock server "
                "before running this test.\n"
                "For mock-based load testing, use "
                "load_test_mock_llm_service.py instead.",
                "\n".join(issues),
            )
            sys.exit(1)
        logger.info("No mock LLM environment detected.")

    @staticmethod
    def is_port_open(host, port) -> bool:
        """Check if a TCP port is accepting connections."""
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except (ConnectionRefusedError, OSError):
            return False

    @staticmethod
    def find_local_server(args):
        """Locate the neuro-san server process for resource monitoring.

        Returns (server_proc, server_log) tuple.
        """
        if not EnvironmentValidator.is_port_open(args.host, args.port):
            logger.error(
                "No service listening on %s:%s.\n"
                "Start the server first.",
                args.host, args.port,
            )
            sys.exit(1)

        server_proc = None
        for keyword in ["neuro_san_studio", "server_main_loop"]:
            server_proc = ResourceMonitor.find_process(keyword)
            if server_proc is not None:
                logger.info(
                    "Found neuro-san server (PID %s) via %s",
                    server_proc.pid, keyword,
                )
                break

        if server_proc is None:
            server_proc = ResourceMonitor.find_process_by_port(
                args.port,
            )
            if server_proc is not None:
                logger.info(
                    "Found neuro-san server (PID %s) via port %s",
                    server_proc.pid, args.port,
                )

        if server_proc is None:
            logger.info(
                "neuro-san server process not found locally. "
                "Resource monitoring disabled."
            )
            return None, args.server_log

        server_log = args.server_log
        if server_log is None:
            server_log = EnvironmentValidator._auto_detect_server_log(
                server_proc,
            )

        return server_proc, server_log

    @staticmethod
    def _auto_detect_server_log(server_proc):
        """Auto-detect server log from server process CWD."""
        try:
            cwd = server_proc.cwd()
            candidate = os.path.join(cwd, "logs", "server.log")
            if os.path.isfile(candidate):
                logger.info(
                    "  Auto-detected server log: %s", candidate,
                )
                return candidate
            logger.warning(
                "  Server log not found at %s. "
                "Retry monitoring unavailable.",
                candidate,
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            logger.warning(
                "  Could not determine server working directory. "
                "Retry monitoring unavailable.",
            )
        return None


class InputValidator:
    """Validates and resolves user input for load test configuration."""

    @staticmethod
    def resolve_stages(args) -> List[int]:
        """Return the list of concurrency stages to run."""
        if args.ramp:
            if args.stages is not None:
                return [
                    int(s.strip()) for s in args.stages.split(",")
                ]
            return list(DEFAULT_STAGES)
        return [args.num_requests]

    @staticmethod
    def resolve_max_requests(args, stages) -> int:
        """Return the effective max-requests cap."""
        if args.max_requests is not None:
            return args.max_requests
        if args.ramp:
            return sum(stages) * args.num_rounds
        return 100

    @staticmethod
    def confirm_cost(
            args, stages, total_cap, profile=None,
            output_dir=None,
    ) -> Optional[Dict[str, Any]]:
        """Display cost warning and optionally run a dry-run probe.

        With --yes: shows the cost warning and returns immediately.
        Without --yes: fires one probe request with --tokens to
        measure actual token usage, shows the extrapolated cost,
        and asks the user to confirm.

        Returns the probe result dict if a probe was run, else None.
        """
        total_planned = sum(stages) * args.num_rounds
        capped = min(total_planned, total_cap)
        logger.info("\n%s", "=" * 60)
        logger.info("  COST WARNING: REAL LLM CALLS")
        logger.info("=" * 60)
        if args.ramp:
            logger.info("  Ramp-up stages: %s", stages)
            logger.info("  Rounds: %s", args.num_rounds)
        logger.info("  Total planned requests: %s", total_planned)
        if capped < total_planned:
            logger.info(
                "  Capped by --max-requests: %s", capped,
            )

        if profile and profile.estimated_tokens_per_request:
            total_tokens = (
                capped * profile.estimated_tokens_per_request
            )
            logger.info(
                "  Estimated tokens: %s × %s = ~%s tokens",
                capped,
                f"{profile.estimated_tokens_per_request:,}",
                f"{total_tokens:,}",
            )
        else:
            logger.info(
                "  Each request involves multiple recursive "
                "LLM calls."
            )
            logger.info(
                "  Estimated cost depends on model and prompt "
                "complexity."
            )

        logger.info("=" * 60)

        if args.yes:
            return None

        return InputValidator._run_cost_probe(
            args, profile, capped, output_dir,
        )

    @staticmethod
    def _run_cost_probe(
            args, profile, total_requests, output_dir,
    ) -> Optional[Dict[str, Any]]:
        """Fire one probe request with --tokens and confirm cost."""
        logger.info(
            "\nRunning 1 dry-run probe to measure actual cost...",
        )

        original_include = args.include_tokens
        args.include_tokens = True
        probe_result = TrafficRunner.run_one(
            args, profile,
            request_id=1, global_request_id=0,
            output_dir=output_dir,
        )
        args.include_tokens = original_include

        probe_tokens = probe_result.get("total_tokens", 0)
        probe_cost = probe_result.get("cost_usd", 0.0)
        probe_model = probe_result.get("model", "unknown")
        probe_status = probe_result.get("status", "FAILED")
        probe_elapsed = probe_result.get("elapsed", 0)

        logger.info(
            "  Probe result: %s in %.1fs",
            probe_status, probe_elapsed,
        )
        logger.info(
            "  Probe tokens: %s (model: %s, cost: $%.6f)",
            f"{probe_tokens:,}", probe_model, probe_cost,
        )

        if probe_tokens > 0:
            est_total_cost = probe_cost * total_requests
            est_total_tokens = probe_tokens * total_requests
            logger.info(
                "  Estimated total for %s requests: "
                "~%s tokens (~$%.4f)",
                total_requests,
                f"{est_total_tokens:,}",
                est_total_cost,
            )
        else:
            logger.info(
                "  No token data from probe (agent may not "
                "track tokens)."
            )

        answer = input(
            "\nProceed with remaining "
            f"{total_requests - 1} requests? [y/N]: ",
        ).strip().lower()
        if answer not in ("y", "yes"):
            logger.info("Aborted by user.")
            sys.exit(0)

        return probe_result


class OutputValidator:
    """Counts results and logs server-side request verification."""

    @staticmethod
    def count_results(results) -> Dict[str, int]:
        """Count results by status type."""
        counts = {
            STATUS_CREATED: 0,
            STATUS_FAILED: 0,
            STATUS_TIMEOUT: 0,
            STATUS_KILLED: 0,
        }
        for result in results:
            status = result.get("status", STATUS_FAILED)
            counts[status] = counts.get(status, 0) + 1
        return counts

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    @staticmethod
    def log_stage_results(actual_requests, counts, elapsed, timeout,
                          idle_timeout, skip_reservation_check=False):
        """Log per-stage summary of request results."""
        logger.info("\n  Requests: %s", actual_requests)
        if skip_reservation_check:
            confirm_label = "output fields confirmed"
        else:
            confirm_label = "success criteria met"
        logger.info(
            "    Created: %s  (%s)",
            counts.get(STATUS_CREATED, 0), confirm_label,
        )
        logger.info(
            "    Failed:  %s  (error or crash)",
            counts.get(STATUS_FAILED, 0),
        )
        logger.info(
            "    Timed out: %s  (hit %ss hard cap)",
            counts.get(STATUS_TIMEOUT, 0), timeout,
        )
        logger.info(
            "    Killed:  %s  (no output for %ss, presumed hanging)",
            counts.get(STATUS_KILLED, 0), idle_timeout,
        )
        logger.info(
            "  Duration: %.2fs | Avg: %.2fs per request",
            elapsed,
            elapsed / actual_requests if actual_requests else 0,
        )

    @staticmethod
    def log_retry_activity(retries, total_retries, actual_requests):
        """Log retry activity from server log."""
        logger.info(
            "\n  max_attempts retry activity (from server log):",
        )
        for error_type in RETRY_ERROR_TYPES:
            count = retries.get(error_type, 0)
            logger.info("    %s retries: %s", error_type, count)
        logger.info("    Total retries:  %s", total_retries)
        amplification = (
            (actual_requests + total_retries) / actual_requests
            if actual_requests > 0 else 1.0
        )
        logger.info(
            "    Amplification:  %.2fx "
            "(%s total LLM attempts for %s requests)",
            amplification,
            actual_requests + total_retries,
            actual_requests,
        )

    @staticmethod
    def log_server_validation(
            server_counts, actual_requests, agent_name,
    ):
        """Log server-side request validation from log counts."""
        if server_counts.get("primary_started") is None:
            return
        pri_started = server_counts.get("primary_started")
        pri_finished = server_counts.get("primary_finished")
        total_started = server_counts.get("total_started")
        total_finished = server_counts.get("total_finished")
        internal_calls = total_started - pri_started
        match_label = (
            "OK" if pri_started >= actual_requests else "MISMATCH"
        )
        logger.info(
            "\n  Server-side validation (from server log):",
        )
        logger.info(
            "    %s received:  %s/%s  (%s)",
            agent_name, pri_started, actual_requests, match_label,
        )
        logger.info(
            "    %s completed: %s/%s",
            agent_name, pri_finished, actual_requests,
        )
        if internal_calls > 0:
            logger.info(
                "    Internal calls: %s additional "
                "streaming_chat calls (recursive)",
                internal_calls,
            )
        logger.info(
            "    Total server calls: %s started, %s finished",
            total_started, total_finished,
        )
        if pri_started < actual_requests:
            logger.warning(
                "    WARNING: Server received %s %s requests "
                "but %s were sent",
                pri_started, agent_name, actual_requests,
            )

    @staticmethod
    def log_disconnections(disconnections):
        """Log client disconnections detected in the current stage."""
        if not disconnections:
            return
        logger.warning(
            "\n  Client disconnections detected: %s",
            len(disconnections),
        )
        for disc in disconnections:
            agent = disc.get("agent", "unknown")
            req_id = disc.get("request_id", "unknown")
            logger.warning(
                "    %s: %s still running at disconnect",
                req_id, agent,
            )
