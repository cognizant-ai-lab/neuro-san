#!/usr/bin/env python
"""
Load-test script for neuro-san server using the mock LLM service.

Fires concurrent requests via agent_cli subprocesses, monitors the
neuro-san server and mock LLM server processes for resource leaks
(RSS, FDs, threads, connections), and prints a per-round summary
with an overall leak analysis.

Prerequisites:
    1. Mock LLM server running (Terminal 1):
       python -m tests.mock_llm_server.mock_llm_server --port 8888

    2. Neuro-san server running with OPENAI_API_BASE (Terminal 2):
       export OPENAI_API_BASE=http://localhost:8888/v1
       python -m neuro_san.service.main_loop.server_main_loop

Usage examples:
    # Defaults: math_guy with preset prompt/sly-data, 5 rounds, 10 requests, 10 workers
    python tests/load_tests/load_test_mock_llm_service.py

    # 100 concurrent requests over 3 rounds
    python tests/load_tests/load_test_mock_llm_service.py --num-requests 100 --max-workers 100 --num-rounds 3

    # Different agent network (preset auto-fills prompt, no sly-data)
    python tests/load_tests/load_test_mock_llm_service.py --agent hello_world

    # Override preset prompt for a known agent
    python tests/load_tests/load_test_mock_llm_service.py --agent hello_world --prompt "Say hi to the moon"

    # Unknown agent requires explicit --prompt
    python tests/load_tests/load_test_mock_llm_service.py --agent my_custom_agent --prompt "test input" --no-sly-data

    # Remote neuro-san server (psutil monitoring auto-disabled)
    python tests/load_tests/load_test_mock_llm_service.py --host 172.31.11.243 --port 8080

    # Auto-start servers (no manual setup needed)
    python tests/load_tests/load_test_mock_llm_service.py --auto-start

    # Auto-start with custom mock port
    python tests/load_tests/load_test_mock_llm_service.py --auto-start --mock-port 9999
"""

import argparse
import logging
import os
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


MOCK_REQUEST_TIMEOUT = 120
PROCESS_WAIT_TIMEOUT = 10


class MockLlmLoadTest:  # pylint: disable=too-many-instance-attributes
    """Load test runner for the neuro-san server using mock LLM service."""

    LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

    AGENT_PRESETS = {
        "math_guy": {
            "prompt": "add",
            "sly_data": '{"x": 3, "y": 5}',
        },
        "hello_world": {
            "prompt": "Greet developers that wrote their very first program",
            "sly_data": None,
        },
        "chat_mock_llm_echo": {
            "prompt": "Hello, testing the mock LLM",
            "sly_data": None,
        },
    }

    MOCK_LOG_PATH = "/tmp/mock_llm_server.log"
    SERVER_LOG_PATH = "/tmp/neuro_san_server.log"
    STARTUP_WAIT_SECONDS = 10

    def __init__(self, args):
        """Initialize the load test with parsed command-line arguments."""
        self.args = args
        self.prompt_file = "/tmp/load_test_prompt.txt"
        self.cmd = None
        self.server_proc = None
        self.mock_proc = None
        self._auto_mock_popen = None
        self._auto_server_popen = None
        self._mock_log_fh = None
        self._server_log_fh = None
        self._test_log_path = None
        self._test_log_handler = None
        self._api_base = None

    @staticmethod
    def parse_args():
        """Parse command-line arguments for load test configuration."""
        parser = argparse.ArgumentParser(
            description="Load-test neuro-san server with resource leak detection.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=__doc__,
        )
        parser.add_argument(
            "--agent",
            type=str,
            default="math_guy",
            help="Agent network name to test (default: math_guy)",
        )
        parser.add_argument(
            "--num-requests",
            type=int,
            default=10,
            help="Number of requests per round (default: 10)",
        )
        parser.add_argument(
            "--max-workers",
            type=int,
            default=10,
            help="Max concurrent workers (default: 10)",
        )
        parser.add_argument(
            "--num-rounds",
            type=int,
            default=5,
            help="Number of rounds to run (default: 5)",
        )
        parser.add_argument(
            "--prompt",
            type=str,
            default=None,
            help="Prompt text to send to the agent. "
                 "Auto-filled from preset if agent is known.",
        )
        parser.add_argument(
            "--sly-data",
            type=str,
            default=None,
            help="JSON sly_data string. Auto-filled from preset if agent is known. "
                 "Use --no-sly-data to omit.",
        )
        parser.add_argument(
            "--no-sly-data",
            action="store_true",
            default=False,
            help="Do not pass --sly_data to agent_cli",
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
            "--settle-time",
            type=int,
            default=10,
            help="Seconds to wait after each round for cleanup (default: 10)",
        )
        parser.add_argument(
            "--auto-start",
            action="store_true",
            default=False,
            help="Auto-start mock LLM and neuro-san servers as subprocesses",
        )
        parser.add_argument(
            "--mock-port",
            type=int,
            default=8888,
            help="Mock LLM server port (default: 8888). Used with --auto-start.",
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

    def _build_cli_command(self):
        """
        Build the agent_cli subprocess command list from instance arguments.
        Includes --no_thinking_file to avoid race conditions under concurrency.
        """
        cmd = [
            "python", "-m", "neuro_san.client.agent_cli",
            "--http",
            "--host", self.args.host,
            "--port", str(self.args.port),
            "--agent", self.args.agent,
            "--first_prompt_file", self.prompt_file,
            "--one_shot",
            "--no_thinking_file",
        ]
        if not self.args.no_sly_data:
            cmd.extend(["--sly_data", self.args.sly_data])
        return cmd

    @staticmethod
    def _run_one(request_id, cmd):
        """Execute a single agent_cli request and return timing + status."""
        start = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=MOCK_REQUEST_TIMEOUT,
            check=False,
        )
        elapsed = time.time() - start
        ok = result.returncode == 0
        status = "OK" if ok else "FAIL"
        logger.info("Request %s: %s (%.2fs)", request_id, status, elapsed)
        if not ok:
            # Show last line of stderr for quick diagnosis
            stderr_line = (result.stderr or "").strip().split("\n")[-1]
            logger.info("  stderr: %s", stderr_line)
        return {"ok": ok, "elapsed": elapsed}

    def _run_round(self):
        """Fire num_requests concurrent requests using a thread pool."""
        passed = 0
        failed = 0
        start = time.time()
        with ThreadPoolExecutor(max_workers=self.args.max_workers) as pool:
            futures = [
                pool.submit(self._run_one, i + 1, self.cmd)
                for i in range(self.args.num_requests)
            ]
            for future in futures:
                result = future.result()
                if result.get("ok"):
                    passed += 1
                else:
                    failed += 1
        total_time = time.time() - start
        logger.info("\nResult: %s passed, %s failed in %.2fs", passed, failed, total_time)
        return passed, failed, total_time

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

    def _apply_presets(self):
        """
        Fill in prompt and sly-data from AGENT_PRESETS when the user has not
        provided them explicitly. Abort if the agent is unknown and --prompt
        is missing.
        """
        preset = self.AGENT_PRESETS.get(self.args.agent)

        if self.args.prompt is None:
            if preset is None:
                known = ", ".join(sorted(self.AGENT_PRESETS.keys()))
                logger.error(
                    "No preset for agent '%s'. "
                    "Please provide --prompt explicitly.\n"
                    "Known presets: %s",
                    self.args.agent, known,
                )
                sys.exit(1)
            self.args.prompt = preset.get("prompt")

        if self.args.sly_data is None and not self.args.no_sly_data:
            if preset is not None and preset.get("sly_data") is not None:
                self.args.sly_data = preset.get("sly_data")
            else:
                self.args.no_sly_data = True

    @staticmethod
    def _get_mock_server_port(mock_proc):
        """Extract the --port value from the mock LLM server's command line."""
        try:
            cmdline = mock_proc.cmdline()
            for i, arg in enumerate(cmdline):
                if arg == "--port" and i + 1 < len(cmdline):
                    return cmdline[i + 1]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return "8888"

    @staticmethod
    def _check_server_api_base(server_proc, mock_port):
        """
        Verify that the neuro-san server has OPENAI_API_BASE set and
        that it points to the correct mock LLM server port.
        Exits with an error if not set or mismatched.
        Returns the OPENAI_API_BASE value on success.
        """
        expected_url = f"http://localhost:{mock_port}/v1"
        try:
            server_env = server_proc.environ()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            logger.info("Could not read server environment: %s", exc)
            return None

        api_base = server_env.get("OPENAI_API_BASE")
        if api_base is None:
            logger.error(
                "neuro-san server does not have OPENAI_API_BASE set.\n"
                "  Mock LLM server is running on port %s.\n"
                "  Restart the server with:\n"
                "    export OPENAI_API_BASE=%s\n"
                "    python -m neuro_san.service.main_loop.server_main_loop",
                mock_port, expected_url,
            )
            sys.exit(1)

        logger.info("  OPENAI_API_BASE=%s", api_base)
        if mock_port not in api_base:
            logger.error(
                "OPENAI_API_BASE does not reference port %s.\n"
                "  Mock LLM server is running on port %s,\n"
                "  but OPENAI_API_BASE=%s\n"
                "  Restart the server with:\n"
                "    export OPENAI_API_BASE=%s\n"
                "    python -m neuro_san.service.main_loop.server_main_loop",
                mock_port, mock_port, api_base, expected_url,
            )
            sys.exit(1)
        return api_base

    def _find_local_processes(self):
        """
        Locate neuro-san server and mock LLM server processes.
        Exits with an error if either is not found.
        Also validates the server's OPENAI_API_BASE matches the mock port.
        """
        self.server_proc = self._find_process("server_main_loop")
        self.mock_proc = self._find_process("mock_llm_server")

        if self.server_proc is None:
            logger.error(
                "neuro-san server process not found.\n"
                "Start it with OPENAI_API_BASE pointing to the mock LLM server:\n"
                "  export OPENAI_API_BASE=http://localhost:8888/v1\n"
                "  python -m neuro_san.service.main_loop.server_main_loop"
            )
            sys.exit(1)
        logger.info("Found neuro-san server (PID %s)", self.server_proc.pid)

        if self.mock_proc is None:
            logger.error(
                "mock LLM server process not found.\n"
                "Start the mock LLM server first, then the neuro-san server:\n"
                "  python -m tests.mock_llm_server.mock_llm_server --port 8888\n"
                "Then:\n"
                "  export OPENAI_API_BASE=http://localhost:8888/v1\n"
                "  python -m neuro_san.service.main_loop.server_main_loop"
            )
            sys.exit(1)
        logger.info("Found mock LLM server (PID %s)", self.mock_proc.pid)

        mock_port = self._get_mock_server_port(self.mock_proc)
        self._api_base = self._check_server_api_base(self.server_proc, mock_port)

    def _auto_start_servers(self):
        """Start mock LLM and neuro-san servers as managed subprocesses."""
        mock_port = str(self.args.mock_port)
        api_base = f"http://localhost:{mock_port}/v1"

        logger.info("Auto-starting mock LLM server (log: %s)", self.MOCK_LOG_PATH)
        self._mock_log_fh = open(  # pylint: disable=consider-using-with
            self.MOCK_LOG_PATH, "w", encoding="utf-8",
        )
        self._auto_mock_popen = subprocess.Popen(  # pylint: disable=consider-using-with
            ["python", "-m", "tests.mock_llm_server.mock_llm_server",
             "--port", mock_port],
            stdout=self._mock_log_fh,
            stderr=self._mock_log_fh,
        )

        server_env = {**os.environ, "OPENAI_API_BASE": api_base}
        logger.info("Auto-starting neuro-san server (log: %s)", self.SERVER_LOG_PATH)
        self._server_log_fh = open(  # pylint: disable=consider-using-with
            self.SERVER_LOG_PATH, "w", encoding="utf-8",
        )
        self._auto_server_popen = subprocess.Popen(  # pylint: disable=consider-using-with
            ["python", "-m", "neuro_san.service.main_loop.server_main_loop"],
            stdout=self._server_log_fh,
            stderr=self._server_log_fh,
            env=server_env,
        )

        logger.info(
            "Waiting %ss for servers to start...", self.STARTUP_WAIT_SECONDS,
        )
        time.sleep(self.STARTUP_WAIT_SECONDS)

        if self._auto_mock_popen.poll() is not None:
            logger.error(
                "Mock LLM server exited unexpectedly. Check %s", self.MOCK_LOG_PATH,
            )
            sys.exit(1)

        if self._auto_server_popen.poll() is not None:
            logger.error(
                "Neuro-san server exited unexpectedly. Check %s", self.SERVER_LOG_PATH,
            )
            self._auto_mock_popen.terminate()
            sys.exit(1)

        self.mock_proc = psutil.Process(self._auto_mock_popen.pid)
        self.server_proc = psutil.Process(self._auto_server_popen.pid)

        self._api_base = api_base
        logger.info("Mock LLM server ready (PID %s)", self.mock_proc.pid)
        logger.info("Neuro-san server ready (PID %s)", self.server_proc.pid)
        logger.info("  OPENAI_API_BASE=%s", self._api_base)

    def _stop_servers(self):
        """Terminate auto-started servers and close log file handles."""
        if self._auto_server_popen is not None:
            logger.info(
                "Stopping neuro-san server (PID %s)...",
                self._auto_server_popen.pid,
            )
            self._auto_server_popen.terminate()
            self._auto_server_popen.wait(timeout=PROCESS_WAIT_TIMEOUT)
        if self._auto_mock_popen is not None:
            logger.info(
                "Stopping mock LLM server (PID %s)...",
                self._auto_mock_popen.pid,
            )
            self._auto_mock_popen.terminate()
            self._auto_mock_popen.wait(timeout=PROCESS_WAIT_TIMEOUT)
        if self._server_log_fh is not None:
            self._server_log_fh.close()
        if self._mock_log_fh is not None:
            self._mock_log_fh.close()
        logger.info("Servers stopped.")

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
        """
        Execute all rounds of the load test, collecting snapshots
        and results per round.
        """
        server_rows: List[Tuple] = []
        mock_rows: List[Tuple] = []
        totals = {"passed": 0, "failed": 0, "time": 0.0}

        for round_num in range(1, self.args.num_rounds + 1):
            logger.info("\n%s", "=" * 60)
            logger.info(
                "  ROUND %s of %s (%s requests, %s workers)",
                round_num, self.args.num_rounds,
                self.args.num_requests, self.args.max_workers,
            )
            logger.info("=" * 60)

            before_server = self._snapshot(self.server_proc) if self.server_proc else None
            before_mock = self._snapshot(self.mock_proc) if self.mock_proc else None
            if before_server:
                self._log_snapshot("Server BEFORE", before_server)

            logger.info(
                "\nFiring %s concurrent requests with %s workers...",
                self.args.num_requests, self.args.max_workers,
            )
            passed, failed, elapsed = self._run_round()
            totals.update({
                "passed": totals.get("passed", 0) + passed,
                "failed": totals.get("failed", 0) + failed,
                "time": totals.get("time", 0.0) + elapsed,
            })

            logger.info("\nWaiting %ss for server cleanup...", self.args.settle_time)
            time.sleep(self.args.settle_time)

            after_server = self._snapshot(self.server_proc) if self.server_proc else None
            after_mock = self._snapshot(self.mock_proc) if self.mock_proc else None
            if after_server:
                self._log_snapshot("Server SETTLED", after_server)

            if before_server and after_server:
                server_rows.append(
                    self._build_snapshot_row(round_num, before_server, after_server))
            if before_mock and after_mock:
                mock_rows.append(
                    self._build_snapshot_row(round_num, before_mock, after_mock))

        return server_rows, mock_rows, totals

    @staticmethod
    def _log_overall_deltas(label, rows, num_rounds):
        """Log overall resource deltas between the first and last rounds."""
        first = rows[0]
        last = rows[-1]
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

    def _log_results(self, totals, server_rows, mock_rows):
        """Log the overall results summary and leak analysis tables."""
        total_requests = self.args.num_requests * self.args.num_rounds

        logger.info("\n%s", "=" * 60)
        logger.info("  OVERALL RESULTS")
        logger.info("=" * 60)
        logger.info(
            "  Total requests: %s (%s passed, %s failed)",
            total_requests, totals.get("passed"), totals.get("failed"),
        )
        logger.info("  Total time:     %.2fs", totals.get("time"))
        if total_requests > 0:
            logger.info(
                "  Avg per request: %.2fs", totals.get("time") / total_requests,
            )

        header = ["Round", "Before RSS", "Settled RSS", "RSS Delta",
                  "FDs", "Threads", "Thread Delta",
                  "Conns", "CPU%", "Children"]

        logger.info("\n%s", "=" * 60)
        logger.info(
            "  LEAK ANALYSIS ACROSS %s ROUNDS (%s total requests)",
            self.args.num_rounds, total_requests,
        )
        logger.info("=" * 60)

        if server_rows:
            logger.info("\nNEURO-SAN SERVER:")
            self._log_table(header, server_rows)

        if mock_rows:
            logger.info("\nMOCK LLM SERVER:")
            self._log_table(header, mock_rows)

        if len(server_rows) >= 2:
            self._log_overall_deltas("Server", server_rows, self.args.num_rounds)

        if len(mock_rows) >= 2:
            self._log_overall_deltas("Mock", mock_rows, self.args.num_rounds)

    def _setup_test_log(self):
        """Add a file handler to capture all output to a timestamped log file."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self._test_log_path = f"/tmp/load_test_{timestamp}.log"
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
        """Execute the full load test workflow."""
        self._apply_presets()
        self._setup_test_log()

        with open(self.prompt_file, "w", encoding="utf-8") as prompt_fh:
            prompt_fh.write(self.args.prompt)

        self.cmd = self._build_cli_command()

        is_local = self.args.host in self.LOCAL_HOSTS

        if self.args.auto_start:
            if not is_local:
                logger.error(
                    "--auto-start can only be used with local mode (localhost)."
                )
                sys.exit(1)
            self._auto_start_servers()
        elif is_local:
            self._find_local_processes()
        else:
            logger.info("Remote mode: targeting %s:%s", self.args.host, self.args.port)
            logger.info("  Process monitoring disabled (server is not local)")

        logger.info(
            "\nConfig: agent=%s, requests=%s, workers=%s, rounds=%s, host=%s, port=%s",
            self.args.agent, self.args.num_requests, self.args.max_workers,
            self.args.num_rounds, self.args.host, self.args.port,
        )
        if not self.args.no_sly_data:
            logger.info("  sly_data=%s", self.args.sly_data)
        logger.info("  prompt=\"%s\"", self.args.prompt)
        logger.info("  settle_time=%ss", self.args.settle_time)

        totals = {"passed": 0, "failed": 0, "time": 0.0}
        try:
            server_rows, mock_rows, totals = self._run_rounds()
            self._log_results(totals, server_rows, mock_rows)
            if is_local and not self.args.auto_start:
                logger.info("\n%s", "=" * 60)
                logger.info(
                    "  WARNING: ENVIRONMENT VARIABLE STILL ACTIVE "
                    "ON NEURO-SAN SERVER"
                )
                logger.info("  Key:   OPENAI_API_BASE")
                logger.info("  Value: %s", self._api_base)
                logger.info(
                    "  All agent requests are routed to the mock LLM server."
                )
                logger.info("  To restore normal operation:")
                logger.info("    1. Stop the neuro-san server")
                logger.info("    2. unset OPENAI_API_BASE")
                logger.info(
                    "    3. Restart: python -m neuro_san.service"
                    ".main_loop.server_main_loop"
                )
                logger.info("=" * 60)
        finally:
            if self.args.auto_start:
                self._stop_servers()
            self._finalize_test_log(totals)

    @staticmethod
    def main():
        """Entry point for the load test script."""
        args = MockLlmLoadTest.parse_args()
        test = MockLlmLoadTest(args)
        test.run()


if __name__ == "__main__":
    MockLlmLoadTest.main()
