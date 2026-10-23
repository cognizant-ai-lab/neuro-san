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

from argparse import ArgumentParser
from argparse import Namespace
from argparse import RawDescriptionHelpFormatter
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from inspect import cleandoc
from logging import DEBUG
from logging import FileHandler
from logging import Formatter
from logging import INFO
from logging import Logger
from logging import basicConfig
from logging import getLogger
from os import environ
from os import remove
from os.path import exists
from subprocess import CompletedProcess
from subprocess import Popen
from subprocess import run
from time import perf_counter
from time import sleep
from time import strftime
from typing import Any
from typing import Dict
from typing import KeysView
from typing import List
from typing import Optional
from typing import Tuple

from leaf_common.logging.sensitive_logger import SensitiveLogger
from psutil import AccessDenied
from psutil import NoSuchProcess
from psutil import Process

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.table_formatter import TableFormatter


class MockLlmLoadTest:  # pylint: disable=too-many-instance-attributes
    """
    Load test runner for the neuro-san server using the mock LLM service.

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
        python tests/load_tests/load_test_mock_llm_service.py --agent my_custom_agent \\
            --prompt "test input" --no-sly-data

        # Remote neuro-san server (psutil monitoring auto-disabled)
        python tests/load_tests/load_test_mock_llm_service.py --host 172.31.11.243 --port 8080

        # Auto-start servers (no manual setup needed)
        python tests/load_tests/load_test_mock_llm_service.py --auto-start

        # Auto-start with custom mock port
        python tests/load_tests/load_test_mock_llm_service.py --auto-start --mock-port 9999
    """

    LOGGER: Logger = getLogger(__name__)

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
    PROMPT_FILE_PATH: str = "/tmp/load_test_prompt.txt"
    LOCALHOST: str = "localhost"
    DEFAULT_MOCK_PORT: int = 8888

    def __init__(self, args: Namespace) -> None:
        """
        Initialize the load test with parsed command-line arguments.

        :param args: Parsed command-line arguments from parse_args()
        """
        self.args: Namespace = args
        self.prompt_file: str = MockLlmLoadTest.PROMPT_FILE_PATH
        self.agent_cli_command: Optional[List[str]] = None
        self.server_process: Optional[Process] = None
        self.mock_process: Optional[Process] = None
        self._auto_mock_popen: Optional[Popen] = None
        self._auto_server_popen: Optional[Popen] = None
        self._test_log_path: Optional[str] = None
        self._test_log_handler: Optional[FileHandler] = None
        self._api_base: Optional[str] = None

    @staticmethod
    def main() -> None:
        """
        Entry point for the load test script.
        """
        basicConfig(level=INFO, format="%(message)s")
        args: Namespace = MockLlmLoadTest.parse_args()
        load_test: MockLlmLoadTest = MockLlmLoadTest(args)
        load_test.run()

    @staticmethod
    def parse_args() -> Namespace:
        """
        Parse command-line arguments for load test configuration.

        :return: The parsed command-line arguments
        """
        # --help prints the class docstring (the usage examples) after the flags, without its indentation.
        usage_text: str = cleandoc(MockLlmLoadTest.__doc__)
        parser: ArgumentParser = ArgumentParser(
            description="Load-test neuro-san server with resource leak detection.",
            formatter_class=RawDescriptionHelpFormatter,
            epilog=usage_text,
        )
        parser.add_argument(
            "--agent",
            type=str,
            default="math_guy",
            help="Agent network name to test (default: %(default)s)",
        )
        parser.add_argument("--num-requests", type=int, default=10,
                            help="Number of requests per round (default: %(default)s)")
        parser.add_argument("--max-workers", type=int, default=10, help="Max concurrent workers (default: %(default)s)")
        parser.add_argument("--num-rounds", type=int, default=5, help="Number of rounds to run (default: %(default)s)")
        parser.add_argument(
            "--prompt",
            type=str,
            default=None,
            help="Prompt text to send to the agent. Auto-filled from preset if agent is known.",
        )
        parser.add_argument(
            "--sly-data",
            type=str,
            default=None,
            help="JSON sly_data string. Auto-filled from preset if agent is known. Use --no-sly-data to omit.",
        )
        parser.add_argument(
            "--no-sly-data",
            action="store_true",
            default=False,
            help="Do not pass --sly_data to agent_cli",
        )
        parser.add_argument("--host", type=str, default=MockLlmLoadTest.LOCALHOST,
                            help="Neuro-san server host (default: %(default)s)")
        parser.add_argument("--port", type=int, default=8080, help="Neuro-san server port (default: %(default)s)")
        parser.add_argument(
            "--settle-time",
            dest="settle_time_seconds",
            metavar="SETTLE_TIME",
            type=int,
            default=10,
            help="Seconds to wait after each round for cleanup (default: %(default)s)",
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
            default=MockLlmLoadTest.DEFAULT_MOCK_PORT,
            help="Mock LLM server port (default: %(default)s). Used with --auto-start.",
        )
        return parser.parse_args()

    def run(self) -> None:
        """
        Execute the full load test workflow.

        :raises SystemExit: With code 1 when --auto-start is used with a remote server, or a check aborts the run
        """
        self._apply_presets()
        self._setup_test_log()

        with open(self.prompt_file, "w", encoding="utf-8") as prompt_file_handle:
            prompt_file_handle.write(self.args.prompt)

        self.agent_cli_command = self._build_cli_command()

        is_local: bool = self.args.host in LoadTestConstants.LOCAL_HOSTS

        if self.args.auto_start:
            if not is_local:
                MockLlmLoadTest.LOGGER.error("--auto-start can only be used with local mode (localhost).")
                raise SystemExit(1)
            self._auto_start_servers()
        elif is_local:
            self._find_local_processes()
        else:
            MockLlmLoadTest.LOGGER.info("Remote mode: targeting %s:%s", self.args.host, self.args.port)
            MockLlmLoadTest.LOGGER.info("  Process monitoring disabled (server is not local)")

        MockLlmLoadTest.LOGGER.info(
            "\nConfig: agent=%s, requests=%s, workers=%s, rounds=%s, host=%s, port=%s",
            self.args.agent, self.args.num_requests, self.args.max_workers,
            self.args.num_rounds, self.args.host, self.args.port,
        )
        if not self.args.no_sly_data:
            MockLlmLoadTest.LOGGER.info("  sly_data=%s", self.args.sly_data)
        MockLlmLoadTest.LOGGER.info("  prompt=\"%s\"", self.args.prompt)
        MockLlmLoadTest.LOGGER.info("  settle_time=%ss", self.args.settle_time_seconds)

        totals: Dict[str, float] = {
            "passed": 0,
            "failed": 0,
            "time_seconds": 0.0,
        }
        server_rows: List[Dict[str, Any]] = []
        mock_rows: List[Dict[str, Any]] = []
        try:
            server_rows, mock_rows, totals = self._run_rounds()
            self._log_results(totals, server_rows, mock_rows)
            if is_local and not self.args.auto_start:
                MockLlmLoadTest.LOGGER.info("\n%s", Formatters.SEPARATOR_LINE)
                MockLlmLoadTest.LOGGER.info("  WARNING: ENVIRONMENT VARIABLE STILL ACTIVE ON NEURO-SAN SERVER")
                MockLlmLoadTest.LOGGER.info("  Key:   OPENAI_API_BASE")
                MockLlmLoadTest.LOGGER.info("  Value: %s", self._api_base)
                MockLlmLoadTest.LOGGER.info("  All agent requests are routed to the mock LLM server.")
                MockLlmLoadTest.LOGGER.info("  To restore normal operation:")
                MockLlmLoadTest.LOGGER.info("    1. Stop the neuro-san server")
                MockLlmLoadTest.LOGGER.info("    2. unset OPENAI_API_BASE")
                MockLlmLoadTest.LOGGER.info("    3. Restart: python -m neuro_san.service.main_loop.server_main_loop")
                MockLlmLoadTest.LOGGER.info("%s", Formatters.SEPARATOR_LINE)
        finally:
            if self.args.auto_start:
                self._stop_servers()
            self._finalize_test_log(totals)

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
        start_seconds: float = perf_counter()
        result: CompletedProcess = run(agent_cli_command, capture_output=True, text=True,
                                       timeout=MockLlmLoadTest.MOCK_REQUEST_TIMEOUT_SECONDS, check=False)
        elapsed_seconds: float = perf_counter() - start_seconds
        succeeded: bool = result.returncode == 0
        status: str = "FAIL"
        if succeeded:
            status = "OK"
        MockLlmLoadTest.LOGGER.info("Request %s: %s (%.2fs)", request_id, status, elapsed_seconds)
        if not succeeded:
            # Show last line of stderr for quick diagnosis
            stderr_text: str = result.stderr or ""
            stripped_stderr: str = stderr_text.strip()
            stderr_lines: List[str] = stripped_stderr.split("\n")
            stderr_line: str = stderr_lines[-1]
            MockLlmLoadTest.LOGGER.info("  stderr: %s", stderr_line)
        request_result: Dict[str, Any] = {
            "ok": succeeded,
            "elapsed_seconds": elapsed_seconds,
        }
        return request_result

    def _run_round(self) -> Tuple[int, int, float]:
        """
        Fire num_requests concurrent requests using a thread pool.

        :return: Number of passed requests, number of failed requests, and the round time in seconds
        """
        passed: int = 0
        failed: int = 0
        start_seconds: float = perf_counter()
        with ThreadPoolExecutor(max_workers=self.args.max_workers) as pool:
            futures: List[Future] = []
            request_id: int
            # Submit every request first, numbered from 1, so the requests run at the same time.
            for request_id in range(1, self.args.num_requests + 1):
                request_future: Future = pool.submit(MockLlmLoadTest._run_one, request_id, self.agent_cli_command)
                futures.append(request_future)
            future: Future
            # Wait for each request in submit order and count it as passed or failed.
            for future in futures:
                result: Dict[str, Any] = future.result()
                if result.get("ok"):
                    passed += 1
                else:
                    failed += 1
        round_seconds: float = perf_counter() - start_seconds
        MockLlmLoadTest.LOGGER.info("\nResult: %s passed, %s failed in %.2fs", passed, failed, round_seconds)
        return passed, failed, round_seconds

    def _apply_presets(self) -> None:
        """
        Fill in prompt and sly-data from AGENT_PRESETS when the user has not
        provided them explicitly. Abort if the agent is unknown and --prompt
        is missing.

        :raises SystemExit: With code 1 when the agent has no preset and --prompt is missing
        """
        preset: Optional[Dict[str, Optional[str]]] = MockLlmLoadTest.AGENT_PRESETS.get(self.args.agent)

        if self.args.prompt is None:
            if preset is None:
                preset_names: KeysView[str] = MockLlmLoadTest.AGENT_PRESETS.keys()
                agent_names: List[str] = sorted(preset_names)
                known_agents: str = ", ".join(agent_names)
                MockLlmLoadTest.LOGGER.error(
                    """No preset for agent '%s'. Please provide --prompt explicitly.
Known presets: %s""",
                    self.args.agent, known_agents,
                )
                raise SystemExit(1)
            self.args.prompt = preset.get("prompt")

        if self.args.sly_data is None and not self.args.no_sly_data:
            if preset is not None and preset.get("sly_data") is not None:
                self.args.sly_data = preset.get("sly_data")
            else:
                self.args.no_sly_data = True

    @staticmethod
    def _get_mock_server_port(mock_process: Process) -> str:
        """
        Extract the --port value from the mock LLM server's command line.

        :param mock_process: The running mock LLM server process
        :return: The --port value, or DEFAULT_MOCK_PORT as a string if the command line has none or cannot be read
        """
        cmdline: List[str] = []
        try:
            cmdline = mock_process.cmdline()
            index: int
            arg: str
            # Find "--port" and return the command line item after it.
            for index, arg in enumerate(cmdline):
                if arg == "--port" and index + 1 < len(cmdline):
                    return cmdline[index + 1]
        except (NoSuchProcess, AccessDenied) as error:
            MockLlmLoadTest._log_process_read_error(DEBUG, "Could not read mock process cmdline", error)
        return str(MockLlmLoadTest.DEFAULT_MOCK_PORT)

    @staticmethod
    def _check_server_api_base(server_process: Process, mock_port: str) -> Optional[str]:
        """
        Verify that the neuro-san server has OPENAI_API_BASE set and
        that it points to the correct mock LLM server port.
        Exits with an error if not set or mismatched.

        :param server_process: The running neuro-san server process
        :param mock_port: Port the mock LLM server listens on
        :return: The server's OPENAI_API_BASE value, or None if its environment cannot be read
        :raises SystemExit: With code 1 when OPENAI_API_BASE is not set or does not reference mock_port
        """
        expected_url: str = MockLlmLoadTest._build_mock_api_base(mock_port)
        server_env: Dict[str, str] = {}
        try:
            server_env = server_process.environ()
        except (NoSuchProcess, AccessDenied) as error:
            MockLlmLoadTest._log_process_read_error(INFO, "Could not read server environment", error)
            return None

        api_base: Optional[str] = server_env.get("OPENAI_API_BASE")
        if api_base is None:
            MockLlmLoadTest.LOGGER.error(
                """neuro-san server does not have OPENAI_API_BASE set.
  Mock LLM server is running on port %s.
  Restart the server with:
    export OPENAI_API_BASE=%s
    python -m neuro_san.service.main_loop.server_main_loop""",
                mock_port, expected_url,
            )
            raise SystemExit(1)

        MockLlmLoadTest.LOGGER.info("  OPENAI_API_BASE=%s", api_base)

        # Without the overlay, model-name-only openai configs (math_guy, hello_world) use the
        # Responses API, which the mock does not serve, and every request is a 404. Warn rather
        # than exit: a deployment may pin Chat Completions through a per-network llm_info_file.
        # An empty value counts as unset: the shipped Dockerfiles define AGENT_LLM_INFO_FILE=""
        # and DefaultLlmFactory ignores an empty path just like a missing variable.
        llm_info_file: Optional[str] = server_env.get("AGENT_LLM_INFO_FILE")
        if not llm_info_file:
            MockLlmLoadTest.LOGGER.warning(
                """neuro-san server does not have AGENT_LLM_INFO_FILE set.
  The openai class defaults to the Responses API, which the mock LLM server does not
  serve, so model-name-only agent configs will get HTTP 404 from /v1/responses.
  Restart the server with:
    export AGENT_LLM_INFO_FILE=%s
    export OPENAI_API_BASE=%s
    python -m neuro_san.service.main_loop.server_main_loop""",
                MockLlmLoadTest.CHAT_COMPLETIONS_LLM_INFO_PATH, expected_url,
            )

        if mock_port not in api_base:
            MockLlmLoadTest.LOGGER.error(
                """OPENAI_API_BASE does not reference port %s.
  Mock LLM server is running on port %s,
  but OPENAI_API_BASE=%s
  Restart the server with:
    export OPENAI_API_BASE=%s
    python -m neuro_san.service.main_loop.server_main_loop""",
                mock_port, mock_port, api_base, expected_url,
            )
            raise SystemExit(1)
        return api_base

    @staticmethod
    def _log_process_read_error(level: int, message: str, error: NoSuchProcess | AccessDenied) -> None:
        """
        Log a psutil read error. The error text goes through a SensitiveLogger, which respects the
        LEAF_LOG_SENSITIVE setting; when that is off, the plain logger still logs the message.

        :param level: Logging level, for example DEBUG or INFO
        :param message: What could not be read, without the error text
        :param error: The psutil error that was caught
        """
        sensitive_logger: SensitiveLogger = SensitiveLogger(MockLlmLoadTest.LOGGER)
        if sensitive_logger.should_log():
            sensitive_logger.log(level, "%s: %s", message, error)
        else:
            MockLlmLoadTest.LOGGER.log(level, "%s", message)

    @staticmethod
    def _build_mock_api_base(mock_port: str) -> str:
        """
        Build the OPENAI_API_BASE URL of the local mock LLM server.

        :param mock_port: Port the mock LLM server listens on
        :return: The URL, for example "http://localhost:8888/v1"
        """
        api_base: str = f"http://{MockLlmLoadTest.LOCALHOST}:{mock_port}/v1"
        return api_base

    def _find_local_processes(self) -> None:
        """
        Locate neuro-san server and mock LLM server processes.
        Exits with an error if either is not found.
        Also validates the server's OPENAI_API_BASE matches the mock port.

        :raises SystemExit: With code 1 when a server process is missing or OPENAI_API_BASE does not match
        """
        self.server_process = ResourceMonitor.find_process("server_main_loop")
        self.mock_process = ResourceMonitor.find_process("mock_llm_server")

        default_mock_port: str = str(MockLlmLoadTest.DEFAULT_MOCK_PORT)
        default_api_base: str = MockLlmLoadTest._build_mock_api_base(default_mock_port)
        if self.server_process is None:
            MockLlmLoadTest.LOGGER.error(
                """neuro-san server process not found.
Start it with OPENAI_API_BASE pointing to the mock LLM server:
  export OPENAI_API_BASE=%s
  python -m neuro_san.service.main_loop.server_main_loop""",
                default_api_base,
            )
            raise SystemExit(1)
        MockLlmLoadTest.LOGGER.info("Found neuro-san server (PID %s)", self.server_process.pid)

        if self.mock_process is None:
            MockLlmLoadTest.LOGGER.error(
                """mock LLM server process not found.
Start the mock LLM server first, then the neuro-san server:
  python -m tests.mock_llm_server.mock_llm_server --port %s
Then:
  export OPENAI_API_BASE=%s
  python -m neuro_san.service.main_loop.server_main_loop""",
                MockLlmLoadTest.DEFAULT_MOCK_PORT, default_api_base,
            )
            raise SystemExit(1)
        MockLlmLoadTest.LOGGER.info("Found mock LLM server (PID %s)", self.mock_process.pid)

        mock_port: str = MockLlmLoadTest._get_mock_server_port(self.mock_process)
        self._api_base = MockLlmLoadTest._check_server_api_base(self.server_process, mock_port)

    def _auto_start_servers(self) -> None:
        """
        Start mock LLM and neuro-san servers as managed subprocesses.

        :raises SystemExit: With code 1 when either server exits during startup
        """
        mock_port: str = str(self.args.mock_port)
        api_base: str = MockLlmLoadTest._build_mock_api_base(mock_port)

        MockLlmLoadTest.LOGGER.info("Auto-starting mock LLM server (log: %s)", MockLlmLoadTest.MOCK_LOG_PATH)
        # The child process gets its own copy of the file descriptor, so this method can close the file
        # once Popen returns, and the server keeps writing to the log.
        with open(MockLlmLoadTest.MOCK_LOG_PATH, "w", encoding="utf-8") as mock_log_file:
            self._auto_mock_popen = Popen(  # pylint: disable=consider-using-with
                ["python", "-m", "tests.mock_llm_server.mock_llm_server",
                 "--port", mock_port],
                stdout=mock_log_file,
                stderr=mock_log_file,
            )

        # The overlay keeps openai-class models on Chat Completions, the only endpoint the mock serves.
        server_env: Dict[str, str] = environ.copy()
        server_env["OPENAI_API_BASE"] = api_base
        server_env["AGENT_LLM_INFO_FILE"] = MockLlmLoadTest.CHAT_COMPLETIONS_LLM_INFO_PATH
        MockLlmLoadTest.LOGGER.info("Auto-starting neuro-san server (log: %s)", MockLlmLoadTest.SERVER_LOG_PATH)
        with open(MockLlmLoadTest.SERVER_LOG_PATH, "w", encoding="utf-8") as server_log_file:
            self._auto_server_popen = Popen(  # pylint: disable=consider-using-with
                ["python", "-m", "neuro_san.service.main_loop.server_main_loop"],
                stdout=server_log_file,
                stderr=server_log_file,
                env=server_env,
            )

        MockLlmLoadTest.LOGGER.info("Waiting %ss for servers to start...", MockLlmLoadTest.STARTUP_WAIT_SECONDS)
        sleep(MockLlmLoadTest.STARTUP_WAIT_SECONDS)

        if self._auto_mock_popen.poll() is not None:
            MockLlmLoadTest.LOGGER.error("Mock LLM server exited unexpectedly. Check %s", MockLlmLoadTest.MOCK_LOG_PATH)
            raise SystemExit(1)

        if self._auto_server_popen.poll() is not None:
            MockLlmLoadTest.LOGGER.error("Neuro-san server exited unexpectedly. Check %s",
                                         MockLlmLoadTest.SERVER_LOG_PATH)
            self._auto_mock_popen.terminate()
            raise SystemExit(1)

        self.mock_process = Process(self._auto_mock_popen.pid)
        self.server_process = Process(self._auto_server_popen.pid)

        self._api_base = api_base
        MockLlmLoadTest.LOGGER.info("Mock LLM server ready (PID %s)", self.mock_process.pid)
        MockLlmLoadTest.LOGGER.info("Neuro-san server ready (PID %s)", self.server_process.pid)
        MockLlmLoadTest.LOGGER.info("  OPENAI_API_BASE=%s", self._api_base)
        MockLlmLoadTest.LOGGER.info("  AGENT_LLM_INFO_FILE=%s", MockLlmLoadTest.CHAT_COMPLETIONS_LLM_INFO_PATH)

    def _stop_servers(self) -> None:
        """
        Terminate auto-started servers.
        """
        if self._auto_server_popen is not None:
            MockLlmLoadTest.LOGGER.info("Stopping neuro-san server (PID %s)...", self._auto_server_popen.pid)
            self._auto_server_popen.terminate()
            self._auto_server_popen.wait(timeout=MockLlmLoadTest.PROCESS_WAIT_TIMEOUT_SECONDS)
        if self._auto_mock_popen is not None:
            MockLlmLoadTest.LOGGER.info("Stopping mock LLM server (PID %s)...", self._auto_mock_popen.pid)
            self._auto_mock_popen.terminate()
            self._auto_mock_popen.wait(timeout=MockLlmLoadTest.PROCESS_WAIT_TIMEOUT_SECONDS)
        MockLlmLoadTest.LOGGER.info("Servers stopped.")

    @staticmethod
    def _build_snapshot_row(round_num: int, before_snapshot: Dict[str, Any],
                            after_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build one round's resource numbers from before/after snapshots.

        :param round_num: Round number, starting at 1
        :param before_snapshot: ResourceMonitor.snapshot() taken before the round
        :param after_snapshot: ResourceMonitor.snapshot() taken after the round settled
        :return: "round_num", "before_rss_megabytes", "settled_rss_megabytes", "rss_delta_megabytes", "fds",
                 "before_threads", "settled_threads", "thread_delta", "connections", "cpu_percent" and "children"
        """
        rss_delta_megabytes: float = after_snapshot.get("rss_megabytes") - before_snapshot.get("rss_megabytes")
        thread_delta: int = after_snapshot.get("threads") - before_snapshot.get("threads")
        snapshot_row: Dict[str, Any] = {
            "round_num": round_num,
            "before_rss_megabytes": before_snapshot.get("rss_megabytes"),
            "settled_rss_megabytes": after_snapshot.get("rss_megabytes"),
            "rss_delta_megabytes": rss_delta_megabytes,
            "fds": after_snapshot.get("fds"),
            "before_threads": before_snapshot.get("threads"),
            "settled_threads": after_snapshot.get("threads"),
            "thread_delta": thread_delta,
            "connections": after_snapshot.get("connections"),
            "cpu_percent": after_snapshot.get("cpu_percent"),
            "children": after_snapshot.get("children"),
        }
        return snapshot_row

    @staticmethod
    def _format_snapshot_row(snapshot_row: Dict[str, Any]) -> List[str]:
        """
        Format one row from _build_snapshot_row() as table cells.

        :param snapshot_row: Row from _build_snapshot_row()
        :return: Cell text in the column order of the header in _log_results()
        """
        round_num: int = snapshot_row.get("round_num")
        before_rss_megabytes: float = snapshot_row.get("before_rss_megabytes")
        settled_rss_megabytes: float = snapshot_row.get("settled_rss_megabytes")
        rss_delta_megabytes: float = snapshot_row.get("rss_delta_megabytes")
        fds: Optional[int] = snapshot_row.get("fds")
        before_threads: Optional[int] = snapshot_row.get("before_threads")
        settled_threads: Optional[int] = snapshot_row.get("settled_threads")
        thread_delta: int = snapshot_row.get("thread_delta")
        connections: Optional[int] = snapshot_row.get("connections")
        cpu_percent: float = snapshot_row.get("cpu_percent")
        children: Optional[int] = snapshot_row.get("children")
        cells: List[str] = [
            str(round_num),
            f"{before_rss_megabytes:.1f} MB",
            f"{settled_rss_megabytes:.1f} MB",
            f"+{rss_delta_megabytes:.1f} MB",
            str(fds),
            f"{before_threads} -> {settled_threads}",
            f"+{thread_delta}",
            str(connections),
            f"{cpu_percent:.1f}%",
            str(children),
        ]
        return cells

    @staticmethod
    def _log_snapshot_table(header: List[str], snapshot_rows: List[Dict[str, Any]]) -> None:
        """
        Log the per-round resource table.

        :param header: Column names
        :param snapshot_rows: Rows from _build_snapshot_row(), one per round
        """
        table_rows: List[List[str]] = []
        snapshot_row: Dict[str, Any]
        # Format each round's row as table cells.
        for snapshot_row in snapshot_rows:
            cells: List[str] = MockLlmLoadTest._format_snapshot_row(snapshot_row)
            table_rows.append(cells)
        TableFormatter.log_table(header, table_rows)

    def _run_rounds(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, float]]:
        """
        Execute all rounds of the load test, collecting snapshots
        and results per round.

        :return: Server rows and mock rows from _build_snapshot_row(), and totals with
                 "passed", "failed" and "time_seconds"
        """
        server_rows: List[Dict[str, Any]] = []
        mock_rows: List[Dict[str, Any]] = []
        totals: Dict[str, float] = {
            "passed": 0,
            "failed": 0,
            "time_seconds": 0.0,
        }
        passed: int = 0
        failed: int = 0
        elapsed_seconds: float = 0.0

        round_num: int
        # Run each round, numbered from 1, with resource snapshots before and after it.
        for round_num in range(1, self.args.num_rounds + 1):
            MockLlmLoadTest.LOGGER.info("\n%s", Formatters.SEPARATOR_LINE)
            MockLlmLoadTest.LOGGER.info(
                "  ROUND %s of %s (%s requests, %s workers)",
                round_num, self.args.num_rounds,
                self.args.num_requests, self.args.max_workers,
            )
            MockLlmLoadTest.LOGGER.info("%s", Formatters.SEPARATOR_LINE)

            before_server: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(self.server_process)
            before_mock: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(self.mock_process)
            if before_server:
                ResourceMonitor.log_snapshot("Server BEFORE", before_server)

            MockLlmLoadTest.LOGGER.info(
                "\nFiring %s concurrent requests with %s workers...",
                self.args.num_requests, self.args.max_workers,
            )
            passed, failed, elapsed_seconds = self._run_round()
            # Plain key assignments: 3 more locals would pass pylint's 15-local limit (R0914).
            totals["passed"] = totals.get("passed", 0) + passed
            totals["failed"] = totals.get("failed", 0) + failed
            totals["time_seconds"] = totals.get("time_seconds", 0.0) + elapsed_seconds

            MockLlmLoadTest.LOGGER.info("\nWaiting %ss for server cleanup...", self.args.settle_time_seconds)
            sleep(self.args.settle_time_seconds)

            after_server: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(self.server_process)
            after_mock: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(self.mock_process)
            if after_server:
                ResourceMonitor.log_snapshot("Server AFTER", after_server)

            if before_server and after_server:
                server_row: Dict[str, Any] = MockLlmLoadTest._build_snapshot_row(round_num, before_server, after_server)
                server_rows.append(server_row)
            if before_mock and after_mock:
                mock_row: Dict[str, Any] = MockLlmLoadTest._build_snapshot_row(round_num, before_mock, after_mock)
                mock_rows.append(mock_row)

        return server_rows, mock_rows, totals

    @staticmethod
    def _log_overall_deltas(label: str, rows: List[Dict[str, Any]], num_rounds: int) -> None:
        """
        Log overall resource deltas between the first and last rounds.

        :param label: Process name shown in the heading ("Server" or "Mock")
        :param rows: Rows from _build_snapshot_row(), one per round
        :param num_rounds: Number of rounds in the run
        """
        first_row: Dict[str, Any] = rows[0]
        last_row: Dict[str, Any] = rows[-1]
        rss_delta_megabytes: float = last_row.get("settled_rss_megabytes") - first_row.get("before_rss_megabytes")
        fds_delta: int = last_row.get("fds") - first_row.get("fds")
        thread_delta: int = last_row.get("settled_threads") - first_row.get("before_threads")
        connections_delta: int = last_row.get("connections") - first_row.get("connections")
        children_delta: int = last_row.get("children") - first_row.get("children")
        MockLlmLoadTest.LOGGER.info("\n%s overall deltas (round 1 before vs round %s settled):", label, num_rounds)
        MockLlmLoadTest.LOGGER.info("  RSS:         +%.1f MB", rss_delta_megabytes)
        MockLlmLoadTest.LOGGER.info("  FDs:         +%s", fds_delta)
        MockLlmLoadTest.LOGGER.info("  Threads:     +%s", thread_delta)
        MockLlmLoadTest.LOGGER.info("  Connections: +%s", connections_delta)
        MockLlmLoadTest.LOGGER.info("  Children:    +%s", children_delta)

    def _log_results(self, totals: Dict[str, float], server_rows: List[Dict[str, Any]],
                     mock_rows: List[Dict[str, Any]]) -> None:
        """
        Log the overall results summary and leak analysis tables.

        :param totals: Totals from _run_rounds(): "passed", "failed" and "time_seconds"
        :param server_rows: Neuro-san server rows from _build_snapshot_row()
        :param mock_rows: Mock LLM server rows from _build_snapshot_row()
        """
        total_requests: int = self.args.num_requests * self.args.num_rounds
        passed: int = totals.get("passed")
        failed: int = totals.get("failed")
        time_seconds: float = totals.get("time_seconds")

        MockLlmLoadTest.LOGGER.info("\n%s", Formatters.SEPARATOR_LINE)
        MockLlmLoadTest.LOGGER.info("  OVERALL RESULTS")
        MockLlmLoadTest.LOGGER.info("%s", Formatters.SEPARATOR_LINE)
        MockLlmLoadTest.LOGGER.info("  Total requests: %s (%s passed, %s failed)", total_requests, passed, failed)
        MockLlmLoadTest.LOGGER.info("  Total time:     %.2fs", time_seconds)
        if total_requests > 0:
            avg_request_seconds: float = time_seconds / total_requests
            MockLlmLoadTest.LOGGER.info("  Avg per request: %.2fs", avg_request_seconds)

        header: List[str] = ["Round", "Before RSS", "Settled RSS", "RSS Delta",
                             "FDs", "Threads", "Thread Delta",
                             "Conns", "CPU%", "Children"]

        MockLlmLoadTest.LOGGER.info("\n%s", Formatters.SEPARATOR_LINE)
        MockLlmLoadTest.LOGGER.info("  LEAK ANALYSIS ACROSS %s ROUNDS (%s total requests)",
                                    self.args.num_rounds, total_requests)
        MockLlmLoadTest.LOGGER.info("%s", Formatters.SEPARATOR_LINE)

        if server_rows:
            MockLlmLoadTest.LOGGER.info("\nNEURO-SAN SERVER:")
            MockLlmLoadTest._log_snapshot_table(header, server_rows)

        if mock_rows:
            MockLlmLoadTest.LOGGER.info("\nMOCK LLM SERVER:")
            MockLlmLoadTest._log_snapshot_table(header, mock_rows)

        if len(server_rows) >= 2:
            MockLlmLoadTest._log_overall_deltas("Server", server_rows, self.args.num_rounds)

        if len(mock_rows) >= 2:
            MockLlmLoadTest._log_overall_deltas("Mock", mock_rows, self.args.num_rounds)

    def _setup_test_log(self) -> None:
        """
        Add a file handler to capture all output to a timestamped log file.
        """
        timestamp: str = strftime("%Y%m%d_%H%M%S")
        self._test_log_path = f"/tmp/load_test_{timestamp}.log"
        self._test_log_handler = FileHandler(self._test_log_path, encoding="utf-8")
        self._test_log_handler.setLevel(INFO)
        test_log_formatter: Formatter = Formatter("%(message)s")
        self._test_log_handler.setFormatter(test_log_formatter)
        # On the root logger, so the file also gets the lines that TableFormatter and ResourceMonitor log.
        root_logger: Logger = getLogger()
        root_logger.addHandler(self._test_log_handler)

    def _finalize_test_log(self, totals: Dict[str, float]) -> None:
        """
        Keep the log file if there were failures, otherwise remove it.

        :param totals: Totals from _run_rounds(); only "failed" is read
        """
        if self._test_log_handler is not None:
            root_logger: Logger = getLogger()
            root_logger.removeHandler(self._test_log_handler)
            self._test_log_handler.close()
        if self._test_log_path is None:
            return
        if totals.get("failed", 0) > 0:
            MockLlmLoadTest.LOGGER.info("\nTest log saved: %s", self._test_log_path)
        elif exists(self._test_log_path):
            remove(self._test_log_path)


if __name__ == "__main__":
    MockLlmLoadTest.main()
