#!/usr/bin/env python
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

"""
Load-test script for neuro-san server using the mock LLM service.

Fires concurrent requests via agent_cli subprocesses, monitors the
neuro-san server and mock LLM server processes for resource leaks
(RSS, FDs, threads, connections), and prints a per-round summary
with an overall leak analysis.

Prerequisites:
    1. Mock LLM server running (Terminal 1):
       python -m tests.mock_llm_server.mock_llm_server --port 8888

    2. Neuro-san server running with OPENAI_API_BASE and the Chat Completions
       llm_info overlay (Terminal 2). The openai class defaults to the Responses
       API, which the mock does not serve, so the overlay pins Chat Completions:
       export AGENT_LLM_INFO_FILE=tests/mock_llm_server/llm_info_chat_completions.hocon
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

import logging
import os
import subprocess
import sys
import time
from argparse import ArgumentParser
from argparse import Namespace
from argparse import RawDescriptionHelpFormatter
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from logging import FileHandler
from logging import Logger
from subprocess import CompletedProcess
from subprocess import Popen
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import TextIO
from typing import Tuple

import psutil

from tests.load_tests.config import LOCAL_HOSTS
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger: Logger = logging.getLogger(__name__)


class MockLlmLoadTest:  # pylint: disable=too-many-instance-attributes
    """
    Load test runner for the neuro-san server using mock LLM service.
    """

    MOCK_REQUEST_TIMEOUT_SECONDS: int = 120
    PROCESS_WAIT_TIMEOUT_SECONDS: int = 10
    # Sparse llm_info overlay that pins openai-class models to Chat Completions, which is the only
    # endpoint the mock LLM server implements. Relative to the repo root, like the -m module paths.
    CHAT_COMPLETIONS_LLM_INFO_PATH: str = "tests/mock_llm_server/llm_info_chat_completions.hocon"

    AGENT_PRESETS: Dict[str, Dict[str, Optional[str]]] = {
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

    MOCK_LOG_PATH: str = "/tmp/mock_llm_server.log"
    SERVER_LOG_PATH: str = "/tmp/neuro_san_server.log"
    STARTUP_WAIT_SECONDS: int = 10

    def __init__(self, args: Namespace) -> None:
        """
        Initialize the load test with parsed command-line arguments.

        :param args: Parsed command-line arguments from parse_args()
        """
        self.args: Namespace = args
        self.prompt_file: str = "/tmp/load_test_prompt.txt"
        self.agent_cli_command: Optional[List[str]] = None
        self.server_process: Optional[psutil.Process] = None
        self.mock_process: Optional[psutil.Process] = None
        self._auto_mock_popen: Optional[Popen] = None
        self._auto_server_popen: Optional[Popen] = None
        self._mock_log_file_handle: Optional[TextIO] = None
        self._server_log_file_handle: Optional[TextIO] = None
        self._test_log_path: Optional[str] = None
        self._test_log_handler: Optional[FileHandler] = None
        self._api_base: Optional[str] = None

    @staticmethod
    def parse_args() -> Namespace:
        """
        Parse command-line arguments for load test configuration.

        :return: The parsed command-line arguments
        """
        parser: ArgumentParser = ArgumentParser(
            description="Load-test neuro-san server with resource leak detection.",
            formatter_class=RawDescriptionHelpFormatter,
            epilog=__doc__,
        )
        parser.add_argument(
            "--agent",
            type=str,
            default="math_guy",
            help="Agent network name to test (default: math_guy)",
        )
        parser.add_argument("--num-requests", type=int, default=10, help="Number of requests per round (default: 10)")
        parser.add_argument("--max-workers", type=int, default=10, help="Max concurrent workers (default: 10)")
        parser.add_argument("--num-rounds", type=int, default=5, help="Number of rounds to run (default: 5)")
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
        parser.add_argument("--host", type=str, default="localhost", help="Neuro-san server host (default: localhost)")
        parser.add_argument("--port", type=int, default=8080, help="Neuro-san server port (default: 8080)")
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

    def _build_cli_command(self) -> List[str]:
        """
        Build the agent_cli subprocess command list from instance arguments.
        Includes --no_thinking_file to avoid race conditions under concurrency.

        :return: The agent_cli command and its arguments, one list item each
        """
        agent_cli_command: List[str] = [
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
            agent_cli_command.extend(["--sly_data", self.args.sly_data])
        return agent_cli_command

    @staticmethod
    def _run_one(request_id: int, agent_cli_command: List[str]) -> Dict[str, Any]:
        """
        Execute a single agent_cli request and return timing + status.

        :param request_id: Number of the request in its round, starting at 1
        :param agent_cli_command: The agent_cli command from _build_cli_command()
        :return: "ok" (bool, exit code 0) and "elapsed_seconds" (float)
        """
        start_seconds: float = time.time()
        result: CompletedProcess = subprocess.run(agent_cli_command, capture_output=True, text=True,
                                                  timeout=MockLlmLoadTest.MOCK_REQUEST_TIMEOUT_SECONDS, check=False)
        elapsed_seconds: float = time.time() - start_seconds
        succeeded: bool = result.returncode == 0
        status: str = "OK" if succeeded else "FAIL"
        logger.info("Request %s: %s (%.2fs)", request_id, status, elapsed_seconds)
        if not succeeded:
            # Show last line of stderr for quick diagnosis
            stderr_line: str = (result.stderr or "").strip().split("\n")[-1]
            logger.info("  stderr: %s", stderr_line)
        return {"ok": succeeded, "elapsed_seconds": elapsed_seconds}

    def _run_round(self) -> Tuple[int, int, float]:
        """
        Fire num_requests concurrent requests using a thread pool.

        :return: Number of passed requests, number of failed requests, and the round time in seconds
        """
        passed: int = 0
        failed: int = 0
        start_seconds: float = time.time()
        with ThreadPoolExecutor(max_workers=self.args.max_workers) as pool:
            futures: List[Future] = [
                pool.submit(self._run_one, i + 1, self.agent_cli_command)
                for i in range(self.args.num_requests)
            ]
            for future in futures:
                result: Dict[str, Any] = future.result()
                if result.get("ok"):
                    passed += 1
                else:
                    failed += 1
        round_seconds: float = time.time() - start_seconds
        logger.info("\nResult: %s passed, %s failed in %.2fs", passed, failed, round_seconds)
        return passed, failed, round_seconds

    @staticmethod
    def _log_table(header: List[str], rows: List[Tuple[str, ...]]) -> None:
        """
        Log an aligned table given a header list and list-of-lists rows.

        :param header: Column names
        :param rows: Rows of cell text, one per column
        """
        column_widths_characters: List[int] = [len(h) for h in header]
        for row in rows:
            for i, val in enumerate(row):
                column_widths_characters[i] = max(column_widths_characters[i], len(str(val)))
        fmt: str = "  ".join(f"{{:>{w}}}" for w in column_widths_characters)
        logger.info("%s", fmt.format(*header))
        logger.info("%s", "-" * (sum(column_widths_characters) + 2 * (len(header) - 1)))
        for row in rows:
            logger.info("%s", fmt.format(*row))

    def _apply_presets(self) -> None:
        """
        Fill in prompt and sly-data from AGENT_PRESETS when the user has not
        provided them explicitly. Abort if the agent is unknown and --prompt
        is missing.
        """
        preset: Optional[Dict[str, Optional[str]]] = self.AGENT_PRESETS.get(self.args.agent)

        if self.args.prompt is None:
            if preset is None:
                known_agents: str = ", ".join(sorted(self.AGENT_PRESETS.keys()))
                logger.error(
                    "No preset for agent '%s'. Please provide --prompt explicitly.\n"
                    "Known presets: %s",
                    self.args.agent, known_agents,
                )
                sys.exit(1)
            self.args.prompt = preset.get("prompt")

        if self.args.sly_data is None and not self.args.no_sly_data:
            if preset is not None and preset.get("sly_data") is not None:
                self.args.sly_data = preset.get("sly_data")
            else:
                self.args.no_sly_data = True

    @staticmethod
    def _get_mock_server_port(mock_process: psutil.Process) -> str:
        """
        Extract the --port value from the mock LLM server's command line.

        :param mock_process: The running mock LLM server process
        :return: The --port value, or "8888" if the command line has none or cannot be read
        """
        cmdline: List[str] = []
        try:
            cmdline = mock_process.cmdline()
            for index, arg in enumerate(cmdline):
                if arg == "--port" and index + 1 < len(cmdline):
                    return cmdline[index + 1]
        except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
            logger.debug("Could not read mock process cmdline: %s", error)
        return "8888"

    @staticmethod
    def _check_server_api_base(server_process: psutil.Process, mock_port: str) -> Optional[str]:
        """
        Verify that the neuro-san server has OPENAI_API_BASE set and
        that it points to the correct mock LLM server port.
        Exits with an error if not set or mismatched.

        :param server_process: The running neuro-san server process
        :param mock_port: Port the mock LLM server listens on
        :return: The server's OPENAI_API_BASE value, or None if its environment cannot be read
        """
        expected_url: str = f"http://localhost:{mock_port}/v1"
        server_env: Dict[str, str] = {}
        try:
            server_env = server_process.environ()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
            logger.info("Could not read server environment: %s", error)
            return None

        api_base: Optional[str] = server_env.get("OPENAI_API_BASE")
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

        # Without the overlay, model-name-only openai configs (math_guy, hello_world) use the
        # Responses API, which the mock does not serve, and every request is a 404. Warn rather
        # than exit: a deployment may pin Chat Completions through a per-network llm_info_file.
        # An empty value counts as unset: the shipped Dockerfiles define AGENT_LLM_INFO_FILE=""
        # and DefaultLlmFactory ignores an empty path just like a missing variable.
        llm_info_file: Optional[str] = server_env.get("AGENT_LLM_INFO_FILE")
        if not llm_info_file:
            logger.warning(
                "neuro-san server does not have AGENT_LLM_INFO_FILE set.\n"
                "  The openai class defaults to the Responses API, which the mock LLM server does not\n"
                "  serve, so model-name-only agent configs will get HTTP 404 from /v1/responses.\n"
                "  Restart the server with:\n"
                "    export AGENT_LLM_INFO_FILE=%s\n"
                "    export OPENAI_API_BASE=%s\n"
                "    python -m neuro_san.service.main_loop.server_main_loop",
                MockLlmLoadTest.CHAT_COMPLETIONS_LLM_INFO_PATH, expected_url,
            )

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

    def _find_local_processes(self) -> None:
        """
        Locate neuro-san server and mock LLM server processes.
        Exits with an error if either is not found.
        Also validates the server's OPENAI_API_BASE matches the mock port.
        """
        self.server_process = ResourceMonitor.find_process("server_main_loop")
        self.mock_process = ResourceMonitor.find_process("mock_llm_server")

        if self.server_process is None:
            logger.error(
                "neuro-san server process not found.\n"
                "Start it with OPENAI_API_BASE pointing to the mock LLM server:\n"
                "  export OPENAI_API_BASE=http://localhost:8888/v1\n"
                "  python -m neuro_san.service.main_loop.server_main_loop"
            )
            sys.exit(1)
        logger.info("Found neuro-san server (PID %s)", self.server_process.pid)

        if self.mock_process is None:
            logger.error(
                "mock LLM server process not found.\n"
                "Start the mock LLM server first, then the neuro-san server:\n"
                "  python -m tests.mock_llm_server.mock_llm_server --port 8888\n"
                "Then:\n"
                "  export OPENAI_API_BASE=http://localhost:8888/v1\n"
                "  python -m neuro_san.service.main_loop.server_main_loop"
            )
            sys.exit(1)
        logger.info("Found mock LLM server (PID %s)", self.mock_process.pid)

        mock_port: str = self._get_mock_server_port(self.mock_process)
        self._api_base = self._check_server_api_base(self.server_process, mock_port)

    def _auto_start_servers(self) -> None:
        """
        Start mock LLM and neuro-san servers as managed subprocesses.
        """
        mock_port: str = str(self.args.mock_port)
        api_base: str = f"http://localhost:{mock_port}/v1"

        logger.info("Auto-starting mock LLM server (log: %s)", self.MOCK_LOG_PATH)
        self._mock_log_file_handle = open(  # pylint: disable=consider-using-with
            self.MOCK_LOG_PATH, "w", encoding="utf-8",
        )
        self._auto_mock_popen = Popen(  # pylint: disable=consider-using-with
            ["python", "-m", "tests.mock_llm_server.mock_llm_server",
             "--port", mock_port],
            stdout=self._mock_log_file_handle,
            stderr=self._mock_log_file_handle,
        )

        # The overlay keeps openai-class models on Chat Completions, the only endpoint the mock serves.
        server_env: Dict[str, str] = {**os.environ, "OPENAI_API_BASE": api_base,
                                      "AGENT_LLM_INFO_FILE": self.CHAT_COMPLETIONS_LLM_INFO_PATH}
        logger.info("Auto-starting neuro-san server (log: %s)", self.SERVER_LOG_PATH)
        self._server_log_file_handle = open(  # pylint: disable=consider-using-with
            self.SERVER_LOG_PATH, "w", encoding="utf-8",
        )
        self._auto_server_popen = Popen(  # pylint: disable=consider-using-with
            ["python", "-m", "neuro_san.service.main_loop.server_main_loop"],
            stdout=self._server_log_file_handle,
            stderr=self._server_log_file_handle,
            env=server_env,
        )

        logger.info("Waiting %ss for servers to start...", self.STARTUP_WAIT_SECONDS)
        time.sleep(self.STARTUP_WAIT_SECONDS)

        if self._auto_mock_popen.poll() is not None:
            logger.error("Mock LLM server exited unexpectedly. Check %s", self.MOCK_LOG_PATH)
            sys.exit(1)

        if self._auto_server_popen.poll() is not None:
            logger.error("Neuro-san server exited unexpectedly. Check %s", self.SERVER_LOG_PATH)
            self._auto_mock_popen.terminate()
            sys.exit(1)

        self.mock_process = psutil.Process(self._auto_mock_popen.pid)
        self.server_process = psutil.Process(self._auto_server_popen.pid)

        self._api_base = api_base
        logger.info("Mock LLM server ready (PID %s)", self.mock_process.pid)
        logger.info("Neuro-san server ready (PID %s)", self.server_process.pid)
        logger.info("  OPENAI_API_BASE=%s", self._api_base)
        logger.info("  AGENT_LLM_INFO_FILE=%s", self.CHAT_COMPLETIONS_LLM_INFO_PATH)

    def _stop_servers(self) -> None:
        """
        Terminate auto-started servers and close log file handles.
        """
        if self._auto_server_popen is not None:
            logger.info("Stopping neuro-san server (PID %s)...", self._auto_server_popen.pid)
            self._auto_server_popen.terminate()
            self._auto_server_popen.wait(timeout=self.PROCESS_WAIT_TIMEOUT_SECONDS)
        if self._auto_mock_popen is not None:
            logger.info("Stopping mock LLM server (PID %s)...", self._auto_mock_popen.pid)
            self._auto_mock_popen.terminate()
            self._auto_mock_popen.wait(timeout=self.PROCESS_WAIT_TIMEOUT_SECONDS)
        if self._server_log_file_handle is not None:
            self._server_log_file_handle.close()
        if self._mock_log_file_handle is not None:
            self._mock_log_file_handle.close()
        logger.info("Servers stopped.")

    @staticmethod
    def _build_snapshot_row(round_num: int, before_snapshot: Dict[str, Any],
                            after_snapshot: Dict[str, Any]) -> Tuple[str, ...]:
        """
        Build a summary table row from before/after snapshots.

        :param round_num: Round number, starting at 1
        :param before_snapshot: ResourceMonitor.snapshot() taken before the round
        :param after_snapshot: ResourceMonitor.snapshot() taken after the round settled
        :return: Cell text in the column order of the header in _log_results()
        """
        rss_delta_megabytes: float = after_snapshot.get("rss") - before_snapshot.get("rss")
        thread_delta: int = after_snapshot.get("threads") - before_snapshot.get("threads")
        return (
            str(round_num),
            f"{before_snapshot.get('rss'):.1f}M",
            f"{after_snapshot.get('rss'):.1f}M",
            f"+{rss_delta_megabytes:.1f}M",
            str(after_snapshot.get("fds")),
            f"{before_snapshot.get('threads')} -> {after_snapshot.get('threads')}",
            f"+{thread_delta}",
            str(after_snapshot.get("connections")),
            f"{after_snapshot.get('cpu'):.1f}%",
            str(after_snapshot.get("children")),
        )

    # pylint: disable=too-many-locals
    def _run_rounds(self) -> Tuple[List[Tuple[str, ...]], List[Tuple[str, ...]], Dict[str, float]]:
        """
        Execute all rounds of the load test, collecting snapshots
        and results per round.

        :return: Server rows and mock rows from _build_snapshot_row(), and totals with
                 "passed", "failed" and "time_seconds"
        """
        server_rows: List[Tuple[str, ...]] = []
        mock_rows: List[Tuple[str, ...]] = []
        totals: Dict[str, float] = {"passed": 0, "failed": 0, "time_seconds": 0.0}
        passed: int = 0
        failed: int = 0
        elapsed_seconds: float = 0.0

        for round_num in range(1, self.args.num_rounds + 1):
            logger.info("\n%s", "=" * 60)
            logger.info(
                "  ROUND %s of %s (%s requests, %s workers)",
                round_num, self.args.num_rounds,
                self.args.num_requests, self.args.max_workers,
            )
            logger.info("=" * 60)

            before_server: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(self.server_process)
            before_mock: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(self.mock_process)
            if before_server:
                ResourceMonitor.log_snapshot("Server BEFORE", before_server)

            logger.info(
                "\nFiring %s concurrent requests with %s workers...",
                self.args.num_requests, self.args.max_workers,
            )
            passed, failed, elapsed_seconds = self._run_round()
            totals.update({
                "passed": totals.get("passed", 0) + passed,
                "failed": totals.get("failed", 0) + failed,
                "time_seconds": totals.get("time_seconds", 0.0) + elapsed_seconds,
            })

            logger.info("\nWaiting %ss for server cleanup...", self.args.settle_time)
            time.sleep(self.args.settle_time)

            after_server: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(self.server_process)
            after_mock: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(self.mock_process)
            if after_server:
                ResourceMonitor.log_snapshot("Server AFTER", after_server)

            if before_server and after_server:
                server_rows.append(self._build_snapshot_row(round_num, before_server, after_server))
            if before_mock and after_mock:
                mock_rows.append(self._build_snapshot_row(round_num, before_mock, after_mock))

        return server_rows, mock_rows, totals

    @staticmethod
    def _log_overall_deltas(label: str, rows: List[Tuple[str, ...]], num_rounds: int) -> None:
        """
        Log overall resource deltas between the first and last rounds.

        :param label: Process name shown in the heading ("Server" or "Mock")
        :param rows: Rows from _build_snapshot_row(), one per round
        :param num_rounds: Number of rounds in the run
        """
        first_row: Tuple[str, ...] = rows[0]
        last_row: Tuple[str, ...] = rows[-1]
        logger.info("\n%s overall deltas (round 1 before vs round %s settled):", label, num_rounds)
        logger.info("  RSS:         +%.1f MB", float(last_row[2].rstrip("M")) - float(first_row[1].rstrip("M")))
        logger.info("  FDs:         +%s", int(last_row[4]) - int(first_row[4]))
        logger.info("  Threads:     +%s", int(last_row[5].split(" -> ")[1]) - int(first_row[5].split(" -> ")[0]))
        logger.info("  Connections: +%s", int(last_row[7]) - int(first_row[7]))
        logger.info("  Children:    +%s", int(last_row[9]) - int(first_row[9]))

    def _log_results(self, totals: Dict[str, float], server_rows: List[Tuple[str, ...]],
                     mock_rows: List[Tuple[str, ...]]) -> None:
        """
        Log the overall results summary and leak analysis tables.

        :param totals: Totals from _run_rounds(): "passed", "failed" and "time_seconds"
        :param server_rows: Neuro-san server rows from _build_snapshot_row()
        :param mock_rows: Mock LLM server rows from _build_snapshot_row()
        """
        total_requests: int = self.args.num_requests * self.args.num_rounds

        logger.info("\n%s", "=" * 60)
        logger.info("  OVERALL RESULTS")
        logger.info("=" * 60)
        logger.info(
            "  Total requests: %s (%s passed, %s failed)",
            total_requests, totals.get("passed"), totals.get("failed"),
        )
        logger.info("  Total time:     %.2fs", totals.get("time_seconds"))
        if total_requests > 0:
            logger.info("  Avg per request: %.2fs", totals.get("time_seconds") / total_requests)

        header: List[str] = ["Round", "Before RSS", "Settled RSS", "RSS Delta",
                             "FDs", "Threads", "Thread Delta",
                             "Conns", "CPU%", "Children"]

        logger.info("\n%s", "=" * 60)
        logger.info("  LEAK ANALYSIS ACROSS %s ROUNDS (%s total requests)", self.args.num_rounds, total_requests)
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

    def _setup_test_log(self) -> None:
        """
        Add a file handler to capture all output to a timestamped log file.
        """
        timestamp: str = time.strftime("%Y%m%d_%H%M%S")
        self._test_log_path = f"/tmp/load_test_{timestamp}.log"
        self._test_log_handler = FileHandler(self._test_log_path, encoding="utf-8")
        self._test_log_handler.setLevel(logging.INFO)
        self._test_log_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(self._test_log_handler)

    def _finalize_test_log(self, totals: Dict[str, float]) -> None:
        """
        Keep the log file if there were failures, otherwise remove it.

        :param totals: Totals from _run_rounds(); only "failed" is read
        """
        if self._test_log_handler is not None:
            logger.removeHandler(self._test_log_handler)
            self._test_log_handler.close()
        if self._test_log_path is None:
            return
        if totals.get("failed", 0) > 0:
            logger.info("\nTest log saved: %s", self._test_log_path)
        elif os.path.exists(self._test_log_path):
            os.remove(self._test_log_path)

    def run(self) -> None:
        """
        Execute the full load test workflow.
        """
        self._apply_presets()
        self._setup_test_log()

        with open(self.prompt_file, "w", encoding="utf-8") as prompt_file_handle:
            prompt_file_handle.write(self.args.prompt)

        self.agent_cli_command = self._build_cli_command()

        is_local: bool = self.args.host in LOCAL_HOSTS

        if self.args.auto_start:
            if not is_local:
                logger.error("--auto-start can only be used with local mode (localhost).")
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

        totals: Dict[str, float] = {"passed": 0, "failed": 0, "time_seconds": 0.0}
        server_rows: List[Tuple[str, ...]] = []
        mock_rows: List[Tuple[str, ...]] = []
        try:
            server_rows, mock_rows, totals = self._run_rounds()
            self._log_results(totals, server_rows, mock_rows)
            if is_local and not self.args.auto_start:
                logger.info("\n%s", "=" * 60)
                logger.info("  WARNING: ENVIRONMENT VARIABLE STILL ACTIVE ON NEURO-SAN SERVER")
                logger.info("  Key:   OPENAI_API_BASE")
                logger.info("  Value: %s", self._api_base)
                logger.info("  All agent requests are routed to the mock LLM server.")
                logger.info("  To restore normal operation:")
                logger.info("    1. Stop the neuro-san server")
                logger.info("    2. unset OPENAI_API_BASE")
                logger.info("    3. Restart: python -m neuro_san.service.main_loop.server_main_loop")
                logger.info("=" * 60)
        finally:
            if self.args.auto_start:
                self._stop_servers()
            self._finalize_test_log(totals)

    @staticmethod
    def main() -> None:
        """
        Entry point for the load test script.
        """
        args: Namespace = MockLlmLoadTest.parse_args()
        load_test: MockLlmLoadTest = MockLlmLoadTest(args)
        load_test.run()


if __name__ == "__main__":
    MockLlmLoadTest.main()
