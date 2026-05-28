#!/usr/bin/env python
"""
Load-test script for the Agent Network Designer (AND) using real LLM calls.

Fires concurrent requests via agent_cli subprocesses to generate new agent
networks through AND, monitors the neuro-san server for resource usage and
max_attempts retry behavior, and prints a per-round summary with an overall
analysis.

Phase 1 only: generate agent networks via AND and confirm successful creation.

Prerequisites:
    1. neuro-san server running with neuro-san-studio registries (Terminal 1):
       export AGENT_REGISTRY_PATH=/path/to/neuro-san-studio/registries
       export OPENAI_API_KEY=<your-key>
       python -m neuro_san.service.main_loop.server_main_loop

    2. OPENAI_API_KEY must be set (real LLM calls = real API costs).

Usage examples:
    # Defaults: 3 requests, 3 workers, 1 round
    python tests/load_tests/load_test_and_real_llm.py

    # 10 concurrent requests over 2 rounds
    python tests/load_tests/load_test_and_real_llm.py --num-requests 10 --max-workers 10 --num-rounds 2

    # Cap total requests for cost control
    python tests/load_tests/load_test_and_real_llm.py --max-requests 20 --num-requests 10 --num-rounds 5

    # Same prompt for all requests (collision stress test)
    python tests/load_tests/load_test_and_real_llm.py --same-prompt

    # Remote neuro-san server
    python tests/load_tests/load_test_and_real_llm.py --host 172.31.11.243 --port 8080

    # Skip cost confirmation prompt
    python tests/load_tests/load_test_and_real_llm.py --yes
"""

import argparse
import logging
import os
import re
import subprocess
import sys
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


class AndRealLlmLoadTest:  # pylint: disable=too-many-instance-attributes
    """Load test runner for the AND agent network using real LLM calls (Phase 1)."""

    LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

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

    DEFAULT_TIMEOUT_SECONDS = 600

    RETRY_LOG_PATTERN = re.compile(
        r"retrying from (RateLimit error |)(\w+)"
    )

    def __init__(self, args):
        """Initialize the load test with parsed command-line arguments."""
        self.args = args
        self.server_proc = None
        self._test_log_path = None
        self._test_log_handler = None

    @staticmethod
    def parse_args():
        """Parse command-line arguments for AND load test configuration."""
        parser = argparse.ArgumentParser(
            description="Load-test AND agent network with real LLM calls (Phase 1).",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=__doc__,
        )
        parser.add_argument(
            "--num-requests",
            type=int,
            default=3,
            help="Number of requests per round (default: 3)",
        )
        parser.add_argument(
            "--max-workers",
            type=int,
            default=3,
            help="Max concurrent workers (default: 3)",
        )
        parser.add_argument(
            "--num-rounds",
            type=int,
            default=1,
            help="Number of rounds to run (default: 1)",
        )
        parser.add_argument(
            "--max-requests",
            type=int,
            default=100,
            help="Hard cap on total requests across all rounds (default: 100). "
                 "Cost safeguard for real LLM calls.",
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
            help="Timeout per request in seconds (default: 600). "
                 "AND is recursive so requests take much longer than simple agents.",
        )
        parser.add_argument(
            "--settle-time",
            type=int,
            default=15,
            help="Seconds to wait after each round for cleanup (default: 15)",
        )
        parser.add_argument(
            "--same-prompt",
            action="store_true",
            default=False,
            help="Use the same prompt for all requests (collision stress test). "
                 "Default is varied prompts from a pool.",
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
            help="Path to neuro-san server log file for max_attempts retry monitoring. "
                 "If not provided, retry monitoring is skipped.",
        )
        return parser.parse_args()

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
        cmd = [
            "python", "-m", "neuro_san.client.agent_cli",
            "--http",
            "--host", self.args.host,
            "--port", str(self.args.port),
            "--agent", "agent_network_designer",
            "--first_prompt_file", prompt_file,
            "--one_shot",
            "--no_thinking_file",
        ]
        return cmd

    def _run_one(self, request_id, global_request_id):  # pylint: disable=too-many-locals
        """Execute a single AND request and return timing, status, and output details."""
        prompt = self._get_prompt_for_request(global_request_id)
        prompt_file = f"/tmp/and_load_test_prompt_{global_request_id}.txt"
        with open(prompt_file, "w", encoding="utf-8") as prompt_fh:
            prompt_fh.write(prompt)

        cmd = self._build_cli_command(prompt_file)
        start = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.args.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            logger.info(
                "Request %s: TIMEOUT after %.2fs", request_id, elapsed,
            )
            return {
                "ok": False,
                "elapsed": elapsed,
                "prompt": prompt,
                "reservation_id": None,
                "network_name": None,
                "error": "TIMEOUT",
            }

        elapsed = time.time() - start
        ok = result.returncode == 0

        reservation_id = None
        network_name = None
        stdout = result.stdout or ""

        if ok:
            reservation_id = self._parse_reservation_id(stdout)
            network_name = self._parse_network_name(stdout)

        status = "OK" if ok else "FAIL"
        logger.info("Request %s: %s (%.2fs)", request_id, status, elapsed)
        if reservation_id:
            logger.info("  reservation_id: %s", reservation_id)
        if network_name:
            logger.info("  network_name: %s", network_name)
        if not ok:
            stderr_line = (result.stderr or "").strip().split("\n")[-1]
            logger.info("  stderr: %s", stderr_line)

        # Clean up prompt file
        try:
            os.remove(prompt_file)
        except OSError:
            pass

        return {
            "ok": ok,
            "elapsed": elapsed,
            "prompt": prompt,
            "reservation_id": reservation_id,
            "network_name": network_name,
            "error": None if ok else stderr_line,
        }

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

    def _run_round(self, round_num, global_offset):
        """Fire num_requests concurrent AND requests using a thread pool."""
        passed = 0
        failed = 0
        results_list = []
        start = time.time()
        with ThreadPoolExecutor(max_workers=self.args.max_workers) as pool:
            futures = [
                pool.submit(self._run_one, i + 1, global_offset + i)
                for i in range(self.args.num_requests)
            ]
            for future in futures:
                result = future.result()
                results_list.append(result)
                if result.get("ok"):
                    passed += 1
                else:
                    failed += 1
        total_time = time.time() - start
        logger.info(
            "\nRound %s result: %s passed, %s failed in %.2fs",
            round_num, passed, failed, total_time,
        )
        return passed, failed, total_time, results_list

    def _validate_environment(self):
        """Validate that OPENAI_API_KEY is set before running."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key is None or len(api_key) == 0:
            logger.error(
                "OPENAI_API_KEY is not set.\n"
                "AND requires real LLM calls. Set your API key:\n"
                "  export OPENAI_API_KEY=<your-key>"
            )
            sys.exit(1)
        logger.info("OPENAI_API_KEY is set.")

    def _confirm_cost(self):
        """Display cost warning and ask for confirmation unless --yes is passed."""
        total_requests = self.args.num_requests * self.args.num_rounds
        capped = min(total_requests, self.args.max_requests)
        logger.info("\n%s", "=" * 60)
        logger.info("  COST WARNING: REAL LLM CALLS")
        logger.info("=" * 60)
        logger.info("  Total planned requests: %s", total_requests)
        if capped < total_requests:
            logger.info(
                "  Capped by --max-requests: %s", capped,
            )
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

    def _find_local_server(self):
        """Locate the neuro-san server process for resource monitoring."""
        self.server_proc = self._find_process("server_main_loop")
        if self.server_proc is None:
            logger.info(
                "neuro-san server process not found locally. "
                "Resource monitoring disabled."
            )
        else:
            logger.info(
                "Found neuro-san server (PID %s)", self.server_proc.pid,
            )

    def _read_server_log_position(self):
        """
        Return the current end position of the server log file.
        Used to read only new log entries after a round.
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
        Returns a dict of error_type -> count.
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
    def _build_snapshot_row(round_num, before, after):
        """Build a summary table row from before/after snapshots."""
        rss_delta = after.get("rss") - before.get("rss")
        thread_delta = after.get("threads") - before.get("threads")
        return (
            str(round_num),
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

    # pylint: disable=too-many-locals
    def _run_rounds(self):
        """Execute all rounds of the load test, collecting snapshots and results."""
        server_rows: List[Tuple] = []
        totals = {"passed": 0, "failed": 0, "time": 0.0}
        all_results: List[Dict[str, Any]] = []
        all_retries: Dict[str, int] = {}
        global_offset = 0
        total_cap = self.args.max_requests

        for round_num in range(1, self.args.num_rounds + 1):
            if totals.get("passed", 0) + totals.get("failed", 0) >= total_cap:
                logger.info(
                    "\nReached --max-requests cap (%s). Stopping.", total_cap,
                )
                break

            remaining = total_cap - (totals.get("passed", 0) + totals.get("failed", 0))
            actual_requests = min(self.args.num_requests, remaining)
            if actual_requests < self.args.num_requests:
                logger.info(
                    "\nCapping round %s to %s requests (--max-requests limit)",
                    round_num, actual_requests,
                )
                self.args.num_requests = actual_requests

            logger.info("\n%s", "=" * 60)
            logger.info(
                "  ROUND %s of %s (%s requests, %s workers)",
                round_num, self.args.num_rounds,
                self.args.num_requests, self.args.max_workers,
            )
            logger.info("=" * 60)

            log_pos = self._read_server_log_position()

            before_server = self._snapshot(self.server_proc) if self.server_proc else None
            if before_server:
                self._log_snapshot("Server BEFORE", before_server)

            logger.info(
                "\nFiring %s concurrent AND requests with %s workers...",
                self.args.num_requests, self.args.max_workers,
            )
            passed, failed, elapsed, round_results = self._run_round(
                round_num, global_offset,
            )
            global_offset += self.args.num_requests
            totals["passed"] = totals.get("passed", 0) + passed
            totals["failed"] = totals.get("failed", 0) + failed
            totals["time"] = totals.get("time", 0.0) + elapsed
            all_results.extend(round_results)

            round_retries = self._count_retries_since(log_pos)
            if round_retries:
                logger.info("\n  max_attempts retries this round:")
                for error_type, count in sorted(round_retries.items()):
                    logger.info("    %s: %s", error_type, count)
                    all_retries[error_type] = all_retries.get(error_type, 0) + count

            logger.info(
                "\nWaiting %ss for server cleanup...", self.args.settle_time,
            )
            time.sleep(self.args.settle_time)

            after_server = self._snapshot(self.server_proc) if self.server_proc else None
            if after_server:
                self._log_snapshot("Server SETTLED", after_server)

            if before_server and after_server:
                server_rows.append(
                    self._build_snapshot_row(round_num, before_server, after_server),
                )

        return server_rows, totals, all_results, all_retries

    def _log_results(self, totals, server_rows, all_results, all_retries):
        """Log the overall results summary and analysis tables."""
        total_sent = totals.get("passed", 0) + totals.get("failed", 0)

        logger.info("\n%s", "=" * 60)
        logger.info("  OVERALL RESULTS")
        logger.info("=" * 60)
        logger.info(
            "  Total requests: %s (%s passed, %s failed)",
            total_sent, totals.get("passed"), totals.get("failed"),
        )
        logger.info("  Total time:     %.2fs", totals.get("time"))
        if total_sent > 0:
            logger.info(
                "  Avg per request: %.2fs", totals.get("time") / total_sent,
            )

        # Networks created
        created = [r for r in all_results if r.get("ok")]
        if created:
            logger.info("\n  Networks successfully created: %s", len(created))
            for result in created:
                logger.info(
                    "    %s (reservation: %s, %.2fs)",
                    result.get("network_name", "unknown"),
                    result.get("reservation_id", "none"),
                    result.get("elapsed"),
                )

        # Failures
        failures = [r for r in all_results if not r.get("ok")]
        if failures:
            logger.info("\n  Failed requests: %s", len(failures))
            for result in failures:
                logger.info(
                    "    prompt=%s, error=%s, %.2fs",
                    result.get("prompt", "")[:50],
                    result.get("error", "unknown"),
                    result.get("elapsed"),
                )

        # Retry analysis
        if all_retries:
            logger.info("\n  max_attempts retry totals:")
            for error_type, count in sorted(all_retries.items()):
                logger.info("    %s: %s", error_type, count)
        else:
            logger.info("\n  max_attempts retries: none detected")

        # Server resource table
        if server_rows:
            header = [
                "Round", "Before RSS", "Settled RSS", "RSS Delta",
                "FDs", "Threads", "Thread Delta",
                "Conns", "CPU%", "Children",
            ]
            logger.info("\n%s", "=" * 60)
            logger.info("  SERVER RESOURCE ANALYSIS")
            logger.info("=" * 60)
            logger.info("\nNEURO-SAN SERVER:")
            self._log_table(header, server_rows)

            if len(server_rows) >= 2:
                self._log_overall_deltas("Server", server_rows)

    @staticmethod
    def _log_overall_deltas(label, rows):
        """Log overall resource deltas between the first and last rounds."""
        first = rows[0]
        last = rows[-1]
        num_rounds = len(rows)
        logger.info(
            "\n%s overall deltas (round 1 before vs round %s settled):",
            label, num_rounds,
        )
        logger.info(
            "  RSS:         +%.1f MB",
            float(last[2].rstrip("M")) - float(first[1].rstrip("M")),
        )
        logger.info(
            "  FDs:         +%s",
            int(last[4]) - int(first[4]),
        )
        logger.info(
            "  Threads:     +%s",
            int(last[5].split(" -> ")[1]) - int(first[5].split(" -> ")[0]),
        )
        logger.info(
            "  Connections: +%s",
            int(last[7]) - int(first[7]),
        )
        logger.info(
            "  Children:    +%s",
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

    def _finalize_test_log(self, totals):
        """Keep the log file if there were failures, otherwise remove it."""
        if self._test_log_handler is not None:
            logger.removeHandler(self._test_log_handler)
            self._test_log_handler.close()
        if self._test_log_path is None:
            return
        if totals.get("failed", 0) > 0:
            logger.info("\nTest log saved: %s", self._test_log_path)
        elif os.path.exists(self._test_log_path):
            os.remove(self._test_log_path)

    def run(self):
        """Execute the full AND load test workflow (Phase 1)."""
        self._validate_environment()
        self._confirm_cost()
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
        logger.info(
            "\nConfig: agent=agent_network_designer, requests=%s, workers=%s, "
            "rounds=%s, max_requests=%s, host=%s, port=%s, timeout=%ss, "
            "prompt_mode=%s",
            self.args.num_requests, self.args.max_workers,
            self.args.num_rounds, self.args.max_requests,
            self.args.host, self.args.port, self.args.timeout,
            prompt_mode,
        )
        logger.info("  settle_time=%ss", self.args.settle_time)
        if self.args.server_log:
            logger.info("  server_log=%s", self.args.server_log)

        totals = {"passed": 0, "failed": 0, "time": 0.0}
        try:
            server_rows, totals, all_results, all_retries = self._run_rounds()
            self._log_results(totals, server_rows, all_results, all_retries)
        finally:
            self._finalize_test_log(totals)

    @staticmethod
    def main():
        """Entry point for the AND load test script."""
        args = AndRealLlmLoadTest.parse_args()
        test = AndRealLlmLoadTest(args)
        test.run()


if __name__ == "__main__":
    AndRealLlmLoadTest.main()
