#!/usr/bin/env python
# pylint: disable=too-many-lines
"""
Load-test script for the Agent Network Designer (AND) using real LLM calls.

Fires concurrent requests via agent_cli subprocesses to generate new agent
networks through AND, monitors the neuro-san server for resource usage and
max_attempts retry behavior, and prints a per-stage summary with an overall
ramp-up analysis.

Phase 1 only: generate agent networks via AND and confirm successful creation.

Prerequisites:
    1. neuro-san server running with neuro-san-studio registries (Terminal 1):
       export AGENT_REGISTRY_PATH=/path/to/neuro-san-studio/registries
       export OPENAI_API_KEY=<your-key>
       python -m neuro_san.service.main_loop.server_main_loop

    2. OPENAI_API_KEY must be set (real LLM calls = real API costs).

Usage examples:
    # Flat mode: 3 requests, 3 workers, 1 round
    python tests/load_tests/load_test_and_real_llm.py --yes

    # Flat mode: 10 concurrent requests over 2 rounds
    python tests/load_tests/load_test_and_real_llm.py --num-requests 10 --max-workers 10 --num-rounds 2 --yes

    # Ramp-up mode: default stages 10 -> 30 -> 50 -> 100
    python tests/load_tests/load_test_and_real_llm.py --ramp --yes

    # Ramp-up mode: custom stages
    python tests/load_tests/load_test_and_real_llm.py --ramp --stages 5,10,25,50 --yes

    # Same prompt for all requests (collision stress test)
    python tests/load_tests/load_test_and_real_llm.py --ramp --same-prompt --yes

    # Remote neuro-san server
    python tests/load_tests/load_test_and_real_llm.py --ramp --host 172.31.11.243 --port 8080 --yes

    # With server log for max_attempts retry monitoring
    python tests/load_tests/load_test_and_real_llm.py --ramp --server-log /tmp/neuro_san_server.log --yes
"""

import argparse
import logging
import os
import re
import select
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import psutil

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# Result status constants
STATUS_CREATED = "CREATED"
STATUS_FAILED = "FAILED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_KILLED = "KILLED"

# Tracked retry error types
RETRY_ERROR_TYPES = [
    "RateLimitError",
    "APIError",
    "KeyError",
    "ValueError",
]


class AndRealLlmLoadTest:  # pylint: disable=too-many-instance-attributes
    """Load test runner for the AND agent network using real LLM calls (Phase 1)."""

    LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

    DEFAULT_STAGES = [10, 30, 50, 100]

    PROMPT_POOL = [
        "Create an agent network for a pet grooming salon",
        "Design a multi-agent system for a university admissions office",
        "Build an agent network for a food truck fleet management company",
        "Create an agent network for a veterinary clinic",
        "Design a multi-agent system for a public library",
        "Build an agent network for a car rental agency",
        "Create an agent network for a music festival organizer",
        "Design a multi-agent system for a real estate property manager",
        "Build an agent network for a dental office",
        "Create an agent network for a local farmers market",
        "Design a multi-agent system for a fitness gym",
        "Build an agent network for a travel agency",
        "Create an agent network for a daycare center",
        "Design a multi-agent system for a home renovation contractor",
        "Build an agent network for a catering company",
        "Create an agent network for a dog walking service",
        "Design a multi-agent system for a photography studio",
        "Build an agent network for a landscaping business",
        "Create an agent network for an auto repair shop",
        "Design a multi-agent system for a wedding planning company",
    ]

    DEFAULT_TIMEOUT_SECONDS = 1200
    DEFAULT_IDLE_TIMEOUT_SECONDS = 300

    RETRY_LOG_PATTERN = re.compile(
        r"retrying from (RateLimit error |)(\w+)"
    )
    REQUEST_START_PATTERN = re.compile(
        r"Start .*/streaming_chat"
    )
    REQUEST_FINISH_PATTERN = re.compile(
        r"Finish .*/streaming_chat"
    )
    PRIMARY_START_PATTERN = re.compile(
        r"Start agent_network_designer/streaming_chat"
    )
    PRIMARY_FINISH_PATTERN = re.compile(
        r"Finish agent_network_designer/streaming_chat"
    )

    def __init__(self, args):
        """Initialize the load test with parsed command-line arguments."""
        self.args = args
        self.server_proc = None
        self._test_log_path = None
        self._test_log_handler = None
        self._debug_dir = None

    @staticmethod
    def parse_args():
        """Parse command-line arguments for AND load test configuration."""
        parser = argparse.ArgumentParser(
            description="Load-test AND agent network with real LLM calls (Phase 1).",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=__doc__,
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
            default=AndRealLlmLoadTest.DEFAULT_TIMEOUT_SECONDS,
            help="Hard timeout per request in seconds (default: 1200). "
                 "Safety net to prevent requests from running forever.",
        )
        parser.add_argument(
            "--idle-timeout",
            type=int,
            default=AndRealLlmLoadTest.DEFAULT_IDLE_TIMEOUT_SECONDS,
            help="Kill a request if no output for this many seconds "
                 "(default: 300). Detects hanging requests.",
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
                 "Default is varied prompts from a pool of 20.",
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
            "--debug",
            action="store_true",
            default=False,
            help="Save raw CLI stdout/stderr for each request to a temp "
                 "directory for debugging.",
        )
        parser.add_argument(
            "--skip-reservation-check",
            action="store_true",
            default=False,
            help="Skip reservation_id validation. A request is marked "
                 "CREATED if network_name is present, even without a "
                 "reservation_id. Useful when running without "
                 "AGENT_NETWORK_DESIGNER_USE_RESERVATIONS=true.",
        )
        return parser.parse_args()

    def _resolve_stages(self):
        """
        Return the list of concurrency stages to run.
        In ramp mode, returns parsed --stages or defaults.
        In flat mode, returns a single-element list from --num-requests.
        """
        if self.args.ramp:
            if self.args.stages is not None:
                return [int(s.strip()) for s in self.args.stages.split(",")]
            return list(self.DEFAULT_STAGES)
        return [self.args.num_requests]

    def _resolve_max_requests(self, stages):
        """Return the effective max-requests cap."""
        if self.args.max_requests is not None:
            return self.args.max_requests
        if self.args.ramp:
            return sum(stages) * self.args.num_rounds
        return 100

    @staticmethod
    def _find_process(keyword):
        """Find a running process whose command line contains the given keyword."""
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if keyword in cmdline:
                    return psutil.Process(proc.info.get("pid"))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def _find_process_by_port(port):
        """Find a process listening on the given port."""
        for proc in psutil.process_iter(["pid"]):
            try:
                for conn in proc.net_connections():
                    if conn.status == "LISTEN" and conn.laddr.port == port:
                        return psutil.Process(proc.info.get("pid"))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def _snapshot(proc) -> Optional[Dict[str, Any]]:
        """Capture a point-in-time resource snapshot of a process."""
        try:
            mem = proc.memory_info()
            return {
                "rss": mem.rss / 1024 / 1024,
                "fds": proc.num_fds(),
                "threads": proc.num_threads(),
                "connections": len(proc.net_connections()),
                "children": len(proc.children()),
                "cpu": proc.cpu_percent(interval=0.1),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    @staticmethod
    def _log_snapshot(label, snap):
        """Log a single resource snapshot."""
        if snap is None:
            logger.info("  %s: process not found", label)
            return
        logger.info(
            "  %s: RSS=%.1f MB, FDs=%s, Threads=%s, Conns=%s, CPU=%.1f%%, Children=%s",
            label, snap.get("rss"), snap.get("fds"), snap.get("threads"),
            snap.get("connections"), snap.get("cpu"), snap.get("children"),
        )

    def _get_prompt_for_request(self, request_id):
        """
        Return the prompt text for a given request.
        In same-prompt mode, always returns the first prompt.
        In varied mode, cycles through the pool and appends the request_id.
        """
        if self.args.same_prompt:
            return self.PROMPT_POOL[0]
        base_prompt = self.PROMPT_POOL[request_id % len(self.PROMPT_POOL)]
        return f"{base_prompt} (request {request_id})"

    def _build_cli_command(self, prompt_file):
        """
        Build the agent_cli subprocess command list.
        Includes --no_thinking_file to avoid race conditions under concurrency.
        """
        return [
            "python", "-m", "neuro_san.client.agent_cli",
            "--http",
            "--host", self.args.host,
            "--port", str(self.args.port),
            "--agent", "agent_network_designer",
            "--first_prompt_file", prompt_file,
            "--one_shot",
            "--no_thinking_file",
        ]

    def _run_one(self, request_id, global_request_id):  # pylint: disable=too-many-locals
        """
        Execute a single AND request with idle-timeout detection.
        Uses Popen for incremental output monitoring instead of subprocess.run.
        """
        prompt = self._get_prompt_for_request(global_request_id)
        prompt_file = f"/tmp/and_load_test_prompt_{global_request_id}.txt"
        with open(prompt_file, "w", encoding="utf-8") as prompt_fh:
            prompt_fh.write(prompt)

        cmd = self._build_cli_command(prompt_file)
        start = time.time()
        status, stdout, stderr, returncode = self._execute_with_idle_detection(cmd)
        elapsed = time.time() - start

        reservation_id = self._parse_reservation_id(stdout)
        network_name = self._parse_network_name(stdout)

        self._save_debug_output(request_id, stdout, stderr)

        if status not in (STATUS_TIMEOUT, STATUS_KILLED):
            if self.args.skip_reservation_check:
                passed = returncode == 0 and network_name
            else:
                passed = returncode == 0 and reservation_id and network_name
            status = STATUS_CREATED if passed else STATUS_FAILED

        display_reservation = (
            "skipped" if self.args.skip_reservation_check
            else reservation_id
        )
        self._log_request_result(request_id, status, elapsed, {
            "reservation_id": display_reservation,
            "network_name": network_name,
            "stderr": stderr,
        })
        self._cleanup_prompt_file(prompt_file)
        error_line = self._last_stderr_line(stderr) if status != STATUS_CREATED else None

        return {
            "status": status,
            "elapsed": elapsed,
            "prompt": prompt,
            "reservation_id": reservation_id,
            "network_name": network_name,
            "error": error_line,
        }

    def _execute_with_idle_detection(self, cmd):  # pylint: disable=too-many-locals
        """
        Run a subprocess with idle-timeout and hard-timeout detection.
        Returns (status, stdout, stderr, returncode).
        """
        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []
        status = STATUS_FAILED
        last_activity = time.time()

        # pylint: disable=consider-using-with
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            status = self._monitor_process(proc, stdout_chunks, stderr_chunks,
                                           last_activity)
        except Exception:  # pylint: disable=broad-exception-caught
            proc.kill()
            proc.wait()
            status = STATUS_FAILED

        remaining_out = proc.stdout.read()
        remaining_err = proc.stderr.read()
        if remaining_out:
            stdout_chunks.append(remaining_out)
        if remaining_err:
            stderr_chunks.append(remaining_err)
        proc.wait(timeout=10)

        return status, "".join(stdout_chunks), "".join(stderr_chunks), proc.returncode

    def _monitor_process(self, proc, stdout_chunks, stderr_chunks, last_activity):
        """Monitor a running process for output, idle timeout, and hard timeout."""
        start = time.time()
        while proc.poll() is None:
            elapsed = time.time() - start
            idle_elapsed = time.time() - last_activity

            if elapsed >= self.args.timeout:
                proc.kill()
                proc.wait()
                return STATUS_TIMEOUT

            if idle_elapsed >= self.args.idle_timeout:
                proc.kill()
                proc.wait()
                return STATUS_KILLED

            readable, _, _ = select.select(
                [proc.stdout, proc.stderr], [], [], 5.0,
            )
            for stream in readable:
                chunk = stream.read1(4096) if hasattr(stream, "read1") else ""
                if not chunk:
                    chunk = stream.readline()
                if chunk:
                    last_activity = time.time()
                    if stream == proc.stdout:
                        stdout_chunks.append(chunk)
                    else:
                        stderr_chunks.append(chunk)
        return STATUS_FAILED

    @staticmethod
    def _log_request_result(request_id, status, elapsed, result_info):
        """Log the result of a single request."""
        logger.info("Request %s: %s (%.2fs)", request_id, status, elapsed)
        logger.info("  reservation_id: %s", result_info.get("reservation_id") or "")
        if result_info.get("network_name"):
            logger.info("  network_name: %s", result_info.get("network_name"))
        if status in (STATUS_FAILED, STATUS_TIMEOUT, STATUS_KILLED):
            stderr_line = AndRealLlmLoadTest._last_stderr_line(
                result_info.get("stderr", ""),
            )
            logger.info("  stderr: %s", stderr_line)

    @staticmethod
    def _last_stderr_line(stderr):
        """Extract the last line of stderr for error reporting."""
        stripped = stderr.strip() if stderr else ""
        if not stripped:
            return ""
        return stripped.rsplit("\n", maxsplit=1)[-1]

    def _save_debug_output(self, request_id, stdout, stderr):
        """Save raw CLI output to debug directory when --debug is enabled."""
        if not self.args.debug:
            return
        if self._debug_dir is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            self._debug_dir = f"/tmp/and_load_test_debug_{timestamp}"
            os.makedirs(self._debug_dir, exist_ok=True)
            logger.info("Debug output directory: %s", self._debug_dir)
        stdout_path = os.path.join(self._debug_dir, f"request_{request_id}_stdout.txt")
        stderr_path = os.path.join(self._debug_dir, f"request_{request_id}_stderr.txt")
        with open(stdout_path, "w", encoding="utf-8") as fh:
            fh.write(stdout)
        if stderr and stderr.strip():
            with open(stderr_path, "w", encoding="utf-8") as fh:
                fh.write(stderr)

    @staticmethod
    def _cleanup_prompt_file(prompt_file):
        """Remove the temporary prompt file."""
        try:
            os.remove(prompt_file)
        except OSError:
            pass

    @staticmethod
    def _parse_reservation_id(stdout):
        """Extract reservation_id from agent_cli stdout (sly_data output)."""
        match = re.search(r'"reservation_id"\s*:\s*"([^"]+)"', stdout)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _parse_network_name(stdout):
        """Extract agent_network_name from agent_cli stdout (sly_data output)."""
        match = re.search(r'"agent_network_name"\s*:\s*"([^"]+)"', stdout)
        if match:
            return match.group(1)
        return None

    def _run_stage(self, num_requests, max_workers, global_offset):
        """Fire num_requests concurrent AND requests using a thread pool."""
        results_list: List[Dict[str, Any]] = []
        start = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(self._run_one, i + 1, global_offset + i)
                for i in range(num_requests)
            ]
            for future in futures:
                results_list.append(future.result())
        total_time = time.time() - start
        return total_time, results_list

    @staticmethod
    def _count_results(results):
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

    def _validate_environment(self):
        """Validate that OPENAI_API_KEY is set and no mock LLM is active."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key is None or len(api_key) == 0:
            logger.error(
                "OPENAI_API_KEY is not set.\n"
                "AND requires real LLM calls. Set your API key:\n"
                "  export OPENAI_API_KEY=<your-key>"
            )
            sys.exit(1)
        logger.info("OPENAI_API_KEY is set.")
        self._check_no_mock_environment()

    def _check_no_mock_environment(self):
        """Exit if a mock LLM environment is detected."""
        issues = []
        api_base = os.environ.get("OPENAI_API_BASE")
        if api_base:
            issues.append(f"  OPENAI_API_BASE={api_base}")
        mock_proc = self._find_process("mock_llm_server")
        if mock_proc is not None:
            issues.append(
                f"  mock_llm_server process running (PID {mock_proc.pid})"
            )
        if issues:
            logger.error(
                "Mock LLM environment detected — this test requires "
                "real LLM calls.\n%s\n\n"
                "Unset OPENAI_API_BASE and stop the mock server before "
                "running this test.\n"
                "For mock-based load testing, use load_test_mock_llm_service.py "
                "instead.",
                "\n".join(issues),
            )
            sys.exit(1)
        logger.info("No mock LLM environment detected.")

    def _confirm_cost(self, stages, total_cap):
        """Display cost warning and ask for confirmation unless --yes is passed."""
        total_planned = sum(stages) * self.args.num_rounds
        capped = min(total_planned, total_cap)
        logger.info("\n%s", "=" * 60)
        logger.info("  COST WARNING: REAL LLM CALLS")
        logger.info("=" * 60)
        if self.args.ramp:
            logger.info("  Ramp-up stages: %s", stages)
            logger.info("  Rounds: %s", self.args.num_rounds)
        logger.info("  Total planned requests: %s", total_planned)
        if capped < total_planned:
            logger.info("  Capped by --max-requests: %s", capped)
        logger.info(
            "  Each AND request involves multiple recursive LLM calls."
        )
        logger.info(
            "  Estimated cost depends on model and prompt complexity."
        )
        logger.info("=" * 60)

        if not self.args.yes:
            answer = input("\nProceed? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                logger.info("Aborted by user.")
                sys.exit(0)

    @staticmethod
    def _is_port_open(host, port):
        """Check if a TCP port is accepting connections."""
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except (ConnectionRefusedError, OSError):
            return False

    def _find_local_server(self):
        """Locate the neuro-san server process for resource monitoring."""
        if not self._is_port_open(self.args.host, self.args.port):
            logger.error(
                "No service listening on %s:%s.\n"
                "Start the server via neuro-san-studio:\n"
                "  python -m neuro_san_studio run --server-only",
                self.args.host, self.args.port,
            )
            sys.exit(1)
        self.server_proc = self._find_process("neuro_san_studio")
        if self.server_proc is not None:
            logger.info(
                "Found neuro-san server (PID %s) via neuro_san_studio",
                self.server_proc.pid,
            )
            self._auto_detect_server_log()
            return
        self.server_proc = self._find_process("server_main_loop")
        if self.server_proc is not None:
            logger.info(
                "Found neuro-san server (PID %s) via server_main_loop",
                self.server_proc.pid,
            )
            self._auto_detect_server_log()
            return
        self.server_proc = self._find_process_by_port(self.args.port)
        if self.server_proc is not None:
            logger.info(
                "Found neuro-san server (PID %s) via port %s",
                self.server_proc.pid, self.args.port,
            )
            self._auto_detect_server_log()
            return
        logger.info(
            "neuro-san server process not found locally. "
            "Resource monitoring disabled."
        )

    def _auto_detect_server_log(self):
        """Auto-detect server log from server process CWD when not set."""
        if self.args.server_log:
            return
        try:
            cwd = self.server_proc.cwd()
            candidate = os.path.join(cwd, "logs", "server.log")
            if os.path.isfile(candidate):
                self.args.server_log = candidate
                logger.info("  Auto-detected server log: %s", candidate)
            else:
                logger.warning(
                    "  Server log not found at %s. "
                    "Retry monitoring unavailable.",
                    candidate,
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            logger.warning(
                "  Could not determine server working directory. "
                "Retry monitoring unavailable.",
            )

    def _read_server_log_position(self):
        """
        Return the current end position of the server log file.
        Used to read only new log entries after a stage.
        """
        if self.args.server_log is None:
            return None
        try:
            with open(self.args.server_log, "r", encoding="utf-8") as log_fh:
                log_fh.seek(0, 2)
                return log_fh.tell()
        except (OSError, IOError):
            return None

    def _count_retries_since(self, position):
        """
        Count max_attempts retry log entries in the server log since the given position.
        Returns a dict of error_type -> count for each tracked error type.
        """
        if self.args.server_log is None or position is None:
            return {}
        retry_counts: Dict[str, int] = {}
        try:
            with open(self.args.server_log, "r", encoding="utf-8") as log_fh:
                log_fh.seek(position)
                for line in log_fh:
                    match = self.RETRY_LOG_PATTERN.search(line)
                    if match:
                        error_type = match.group(2)
                        retry_counts[error_type] = retry_counts.get(error_type, 0) + 1
        except (OSError, IOError):
            pass
        return retry_counts

    def _count_requests_since(self, position):
        """
        Count request Start/Finish entries in the server log since the given position.
        Separates primary (agent_network_designer) vs total (all agents) counts.
        """
        if self.args.server_log is None or position is None:
            return {
                "primary_started": None, "primary_finished": None,
                "total_started": None, "total_finished": None,
            }
        primary_started = 0
        primary_finished = 0
        total_started = 0
        total_finished = 0
        try:
            with open(self.args.server_log, "r", encoding="utf-8") as log_fh:
                log_fh.seek(position)
                for line in log_fh:
                    if self.REQUEST_START_PATTERN.search(line):
                        total_started += 1
                    if self.REQUEST_FINISH_PATTERN.search(line):
                        total_finished += 1
                    if self.PRIMARY_START_PATTERN.search(line):
                        primary_started += 1
                    if self.PRIMARY_FINISH_PATTERN.search(line):
                        primary_finished += 1
        except (OSError, IOError):
            pass
        return {
            "primary_started": primary_started,
            "primary_finished": primary_finished,
            "total_started": total_started,
            "total_finished": total_finished,
        }

    def _start_log_monitor(self, position, expected_count, fire_time):
        """
        Start a background thread to monitor server log for initial request arrivals.
        Reports each primary AND request as soon as it appears in the log.
        Returns (stop_event, thread) or (None, None) if monitoring is not available.
        """
        if self.args.server_log is None or position is None:
            return None, None
        stop_event = threading.Event()
        monitor = threading.Thread(
            target=self._log_monitor_worker,
            args=(position, expected_count, stop_event, fire_time),
            daemon=True,
        )
        monitor.start()
        return stop_event, monitor

    def _log_monitor_worker(self, position, expected_count, stop_event,
                            fire_time):
        """Background worker that tails server log and reports AND request arrivals."""
        count = 0
        try:
            with open(self.args.server_log, "r", encoding="utf-8") as log_fh:
                log_fh.seek(position)
                while not stop_event.is_set() and count < expected_count:
                    line = log_fh.readline()
                    if line:
                        if self.PRIMARY_START_PATTERN.search(line):
                            count += 1
                            now = time.time()
                            ts = time.strftime(
                                "%H:%M:%S", time.localtime(now),
                            )
                            delta = now - fire_time
                            logger.info(
                                "  [server] AND request %s/%s "
                                "received [%s] (+%.1fs)",
                                count, expected_count, ts, delta,
                            )
                    else:
                        stop_event.wait(0.5)
        except (OSError, IOError):
            pass

    @staticmethod
    def _log_table(header, rows):
        """Log an aligned table given a header list and list-of-lists rows."""
        col_widths = [len(h) for h in header]
        for row in rows:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(val)))
        fmt = "  ".join(f"{{:>{w}}}" for w in col_widths)
        logger.info("%s", fmt.format(*header))
        logger.info("%s", "-" * (sum(col_widths) + 2 * (len(header) - 1)))
        for row in rows:
            logger.info("%s", fmt.format(*row))

    @staticmethod
    def _build_resource_row(stage_label, before, after):
        """Build a resource summary row from before/after snapshots."""
        rss_delta = after.get("rss") - before.get("rss")
        thread_delta = after.get("threads") - before.get("threads")
        return (
            str(stage_label),
            f"{before.get('rss'):.1f}M",
            f"{after.get('rss'):.1f}M",
            f"+{rss_delta:.1f}M",
            str(after.get("fds")),
            f"{before.get('threads')} -> {after.get('threads')}",
            f"+{thread_delta}",
            str(after.get("connections")),
            f"{after.get('cpu'):.1f}%",
            str(after.get("children")),
        )

    # pylint: disable=too-many-locals,too-many-statements,too-many-branches
    def _run_all_stages(self, stages, total_cap):
        """Execute all stages of the load test, collecting data per stage."""
        stage_summaries: List[Dict[str, Any]] = []
        resource_rows: List[Tuple] = []
        global_offset = 0
        total_sent = 0

        for round_num in range(1, self.args.num_rounds + 1):
            if self.args.num_rounds > 1:
                logger.info("\n%s", "#" * 60)
                logger.info("  ROUND %s of %s", round_num, self.args.num_rounds)
                logger.info("#" * 60)

            for stage_idx, num_concurrent in enumerate(stages):
                if total_sent >= total_cap:
                    logger.info(
                        "\nReached --max-requests cap (%s). Stopping.",
                        total_cap,
                    )
                    return stage_summaries, resource_rows

                remaining = total_cap - total_sent
                actual_requests = min(num_concurrent, remaining)
                stage_num = stage_idx + 1

                logger.info("\n%s", "=" * 60)
                stage_label = f"STAGE {stage_num}: {actual_requests} concurrent connections"
                if self.args.num_rounds > 1:
                    stage_label += f" (round {round_num})"
                logger.info("  %s", stage_label)
                logger.info("=" * 60)

                if actual_requests < num_concurrent:
                    logger.info(
                        "  (Capped from %s to %s by --max-requests)",
                        num_concurrent, actual_requests,
                    )

                log_pos = self._read_server_log_position()

                before_server = (
                    self._snapshot(self.server_proc) if self.server_proc else None
                )
                if before_server:
                    self._log_snapshot("Server BEFORE", before_server)

                fire_time = time.time()
                fire_ts = time.strftime("%H:%M:%S", time.localtime(fire_time))
                logger.info(
                    "\nFiring %s concurrent AND requests... [%s]",
                    actual_requests, fire_ts,
                )
                stop_event, monitor = self._start_log_monitor(
                    log_pos, actual_requests, fire_time,
                )
                elapsed, results = self._run_stage(
                    actual_requests, actual_requests, global_offset,
                )
                if stop_event:
                    stop_event.set()
                if monitor:
                    monitor.join(timeout=2)
                global_offset += actual_requests
                total_sent += actual_requests

                counts = self._count_results(results)
                retries = self._count_retries_since(log_pos)
                server_counts = self._count_requests_since(log_pos)
                total_retries = sum(retries.values())
                amplification = (
                    (actual_requests + total_retries) / actual_requests
                    if actual_requests > 0 else 1.0
                )

                # Log per-stage summary
                logger.info("\n  Requests: %s", actual_requests)
                logger.info(
                    "    Created: %s  (%s)",
                    counts.get(STATUS_CREATED, 0),
                    "network_name confirmed"
                    if self.args.skip_reservation_check
                    else "reservation_id + network_name confirmed",
                )
                logger.info(
                    "    Failed:  %s  (error or crash)",
                    counts.get(STATUS_FAILED, 0),
                )
                logger.info(
                    "    Timed out: %s  (hit %ss hard cap)",
                    counts.get(STATUS_TIMEOUT, 0), self.args.timeout,
                )
                logger.info(
                    "    Killed:  %s  (no output for %ss, presumed hanging)",
                    counts.get(STATUS_KILLED, 0), self.args.idle_timeout,
                )
                logger.info("  Duration: %.2fs | Avg: %.2fs per request",
                            elapsed,
                            elapsed / actual_requests if actual_requests else 0)

                # Log server-side request validation
                if server_counts.get("primary_started") is not None:
                    pri_started = server_counts["primary_started"]
                    pri_finished = server_counts["primary_finished"]
                    total_started = server_counts["total_started"]
                    total_finished = server_counts["total_finished"]
                    internal_calls = total_started - pri_started
                    match_label = (
                        "OK" if pri_started >= actual_requests
                        else "MISMATCH"
                    )
                    logger.info(
                        "\n  Server-side validation (from server log):"
                    )
                    logger.info(
                        "    AND received:  %s/%s  (%s)",
                        pri_started, actual_requests, match_label,
                    )
                    logger.info(
                        "    AND completed: %s/%s",
                        pri_finished, actual_requests,
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
                            "    WARNING: Server received %s AND requests "
                            "but %s were sent",
                            pri_started, actual_requests,
                        )

                # Log retry activity
                if self.args.server_log:
                    logger.info("\n  max_attempts retry activity (from server log):")
                    for error_type in RETRY_ERROR_TYPES:
                        count = retries.get(error_type, 0)
                        logger.info("    %s retries: %s", error_type, count)
                    logger.info("    Total retries:  %s", total_retries)
                    logger.info(
                        "    Amplification:  %.2fx (%s total LLM attempts for %s requests)",
                        amplification,
                        actual_requests + total_retries,
                        actual_requests,
                    )

                # Settle and snapshot
                logger.info(
                    "\n  Waiting %ss for server cleanup...",
                    self.args.settle_time,
                )
                time.sleep(self.args.settle_time)

                after_server = (
                    self._snapshot(self.server_proc) if self.server_proc else None
                )
                if after_server:
                    self._log_snapshot("Server SETTLED", after_server)

                if before_server and after_server:
                    resource_rows.append(
                        self._build_resource_row(
                            f"{actual_requests}",
                            before_server, after_server,
                        ),
                    )

                stage_summaries.append({
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
                })

        return stage_summaries, resource_rows

    def _log_ramp_summary(self, stage_summaries):
        """Log the ramp-up summary table across all stages."""
        logger.info("\n%s", "=" * 60)
        logger.info("  RAMP-UP SUMMARY")
        logger.info("=" * 60)

        has_server_counts = any(
            summary.get("primary_started") is not None
            for summary in stage_summaries
        )
        header = [
            "Stage", "Concurrent", "Created", "Failed",
            "Timeout", "Killed", "Retries", "Amplification",
            "Duration",
        ]
        if has_server_counts:
            header.extend(["AND Recv", "AND Done", "Internal"])
        rows = []
        for summary in stage_summaries:
            counts = summary.get("counts", {})
            row = (
                str(summary.get("stage")),
                str(summary.get("concurrent")),
                str(counts.get(STATUS_CREATED, 0)),
                str(counts.get(STATUS_FAILED, 0)),
                str(counts.get(STATUS_TIMEOUT, 0)),
                str(counts.get(STATUS_KILLED, 0)),
                str(summary.get("total_retries", 0)),
                f"{summary.get('amplification', 1.0):.2f}x",
                f"{summary.get('elapsed', 0):.1f}s",
            )
            if has_server_counts:
                pri_started = summary.get("primary_started")
                pri_finished = summary.get("primary_finished")
                total_started = summary.get("total_started")
                internal = (
                    str(total_started - pri_started)
                    if pri_started is not None and total_started is not None
                    else "-"
                )
                row += (
                    str(pri_started) if pri_started is not None else "-",
                    str(pri_finished) if pri_finished is not None else "-",
                    internal,
                )
            rows.append(row)
        self._log_table(header, rows)

    def _log_overall_results(self, stage_summaries):
        """Log overall results across all stages."""
        total_created = 0
        total_failed = 0
        total_timeout = 0
        total_killed = 0
        total_time = 0.0
        total_retries = 0
        total_requests = 0
        all_results: List[Dict[str, Any]] = []

        for summary in stage_summaries:
            counts = summary.get("counts", {})
            total_created += counts.get(STATUS_CREATED, 0)
            total_failed += counts.get(STATUS_FAILED, 0)
            total_timeout += counts.get(STATUS_TIMEOUT, 0)
            total_killed += counts.get(STATUS_KILLED, 0)
            total_time += summary.get("elapsed", 0)
            total_retries += summary.get("total_retries", 0)
            total_requests += summary.get("concurrent", 0)
            all_results.extend(summary.get("results", []))

        total_sent = total_created + total_failed + total_timeout + total_killed

        logger.info("\n%s", "=" * 60)
        logger.info("  OVERALL RESULTS")
        logger.info("=" * 60)
        logger.info("  Total requests: %s", total_sent)
        logger.info("    Created:   %s", total_created)
        logger.info("    Failed:    %s", total_failed)
        logger.info("    Timed out: %s", total_timeout)
        logger.info("    Killed:    %s", total_killed)
        logger.info("  Total time:  %.2fs", total_time)
        if total_sent > 0:
            logger.info(
                "  Avg per request: %.2fs", total_time / total_sent,
            )

        # Overall retry summary
        if total_retries > 0:
            amplification = (
                (total_requests + total_retries) / total_requests
                if total_requests > 0 else 1.0
            )
            logger.info("\n  Overall max_attempts retry totals:")
            logger.info("    Total retries:   %s", total_retries)
            logger.info("    Amplification:   %.2fx", amplification)

        # Networks created
        created = [r for r in all_results if r.get("status") == STATUS_CREATED]
        if created:
            logger.info("\n  Networks successfully created:")
            for result in created:
                logger.info(
                    "    %s (reservation: %s, %.2fs)",
                    result.get("network_name", "unknown"),
                    result.get("reservation_id", "none"),
                    result.get("elapsed"),
                )

    @staticmethod
    def _log_resource_deltas(resource_rows):
        """Log overall resource deltas if enough data points."""
        if len(resource_rows) < 2:
            return
        first = resource_rows[0]
        last = resource_rows[-1]
        logger.info("\n  Server overall deltas (first stage vs last stage):")
        logger.info(
            "    RSS:         +%.1f MB",
            float(last[2].rstrip("M")) - float(first[1].rstrip("M")),
        )
        logger.info(
            "    FDs:         +%s",
            int(last[4]) - int(first[4]),
        )
        logger.info(
            "    Threads:     +%s",
            int(last[5].split(" -> ")[1]) - int(first[5].split(" -> ")[0]),
        )
        logger.info(
            "    Connections: +%s",
            int(last[7]) - int(first[7]),
        )
        logger.info(
            "    Children:    +%s",
            int(last[9]) - int(first[9]),
        )

    def _setup_test_log(self):
        """Add a file handler to capture all output to a timestamped log file."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self._test_log_path = f"/tmp/and_load_test_{timestamp}.log"
        self._test_log_handler = logging.FileHandler(
            self._test_log_path, encoding="utf-8",
        )
        self._test_log_handler.setLevel(logging.INFO)
        self._test_log_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(self._test_log_handler)

    def _finalize_test_log(self, stage_summaries):
        """Keep the log file if there were failures, otherwise remove it."""
        if self._test_log_handler is not None:
            logger.removeHandler(self._test_log_handler)
            self._test_log_handler.close()
        if self._test_log_path is None:
            return
        has_failures = any(
            summary.get("counts", {}).get(STATUS_FAILED, 0) > 0
            or summary.get("counts", {}).get(STATUS_TIMEOUT, 0) > 0
            or summary.get("counts", {}).get(STATUS_KILLED, 0) > 0
            for summary in stage_summaries
        )
        if has_failures:
            logger.info("\nTest log saved: %s", self._test_log_path)
        elif os.path.exists(self._test_log_path):
            os.remove(self._test_log_path)

    def run(self):
        """Execute the full AND load test workflow (Phase 1)."""
        self._validate_environment()

        stages = self._resolve_stages()
        total_cap = self._resolve_max_requests(stages)

        self._confirm_cost(stages, total_cap)
        self._setup_test_log()

        is_local = self.args.host in self.LOCAL_HOSTS

        if is_local:
            self._find_local_server()
        else:
            logger.info(
                "Remote mode: targeting %s:%s",
                self.args.host, self.args.port,
            )
            logger.info("  Process monitoring disabled (server is not local)")

        prompt_mode = "same" if self.args.same_prompt else "varied"
        mode = "ramp" if self.args.ramp else "flat"
        logger.info(
            "\nConfig: agent=agent_network_designer, mode=%s, "
            "stages=%s, rounds=%s, max_requests=%s, host=%s, port=%s, "
            "timeout=%ss, idle_timeout=%ss, prompt_mode=%s",
            mode, stages, self.args.num_rounds, total_cap,
            self.args.host, self.args.port, self.args.timeout,
            self.args.idle_timeout, prompt_mode,
        )
        logger.info("  settle_time=%ss", self.args.settle_time)
        if self.args.server_log:
            logger.info("  server_log=%s", self.args.server_log)
        if self.args.debug:
            logger.info("  debug=enabled (CLI output saved to /tmp)")

        stage_summaries: List[Dict[str, Any]] = []
        try:
            stage_summaries, resource_rows = self._run_all_stages(
                stages, total_cap,
            )

            if len(stage_summaries) > 1:
                self._log_ramp_summary(stage_summaries)

            self._log_overall_results(stage_summaries)

            if resource_rows:
                resource_header = [
                    "Concurrent", "Before RSS", "Settled RSS", "RSS Delta",
                    "FDs", "Threads", "Thread Delta",
                    "Conns", "CPU%", "Children",
                ]
                logger.info("\n%s", "=" * 60)
                logger.info("  SERVER RESOURCE ANALYSIS")
                logger.info("=" * 60)
                self._log_table(resource_header, resource_rows)
                self._log_resource_deltas(resource_rows)
        finally:
            self._finalize_test_log(stage_summaries)

    @staticmethod
    def main():
        """Entry point for the AND load test script."""
        args = AndRealLlmLoadTest.parse_args()
        test = AndRealLlmLoadTest(args)
        test.run()


if __name__ == "__main__":
    AndRealLlmLoadTest.main()
