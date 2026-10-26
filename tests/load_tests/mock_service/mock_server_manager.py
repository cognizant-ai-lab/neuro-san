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

from argparse import Namespace
from logging import DEBUG
from logging import INFO
from logging import Logger
from logging import getLogger
from os import environ
from subprocess import Popen
from time import sleep
from typing import Dict
from typing import List
from typing import Optional

from leaf_common.logging.sensitive_logger import SensitiveLogger
from psutil import AccessDenied
from psutil import NoSuchProcess
from psutil import Process

from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError


class MockServerManager:
    """
    Finds or starts the neuro-san server and the mock LLM server of the mock LLM load test.

    In local mode it finds both running processes and checks that the neuro-san server sends its
    LLM calls to the mock port. With --auto-start it starts both as subprocesses and stops them at the end.
    The processes it holds are the ones the rounds take resource snapshots of.
    """

    LOGGER: Logger = getLogger(__name__)

    PROCESS_WAIT_TIMEOUT_SECONDS: int = 10
    # Sparse llm_info overlay that pins openai-class models to Chat Completions, which is the only
    # endpoint the mock LLM server implements. Relative to the repo root, like the -m module paths.
    CHAT_COMPLETIONS_LLM_INFO_PATH: str = "tests/mock_llm_server/llm_info_chat_completions.hocon"
    MOCK_LOG_PATH: str = "/tmp/mock_llm_server.log"
    SERVER_LOG_PATH: str = "/tmp/neuro_san_server.log"
    STARTUP_WAIT_SECONDS: int = 10
    LOCALHOST: str = "localhost"
    DEFAULT_MOCK_PORT: int = 8888

    def __init__(self, args: Namespace) -> None:
        """
        Initialize the manager with no server found or started yet.

        :param args: Parsed command-line arguments from MockLoadTestArguments.parse_args()
        """
        self._args: Namespace = args
        self._server_process: Optional[Process] = None
        self._mock_process: Optional[Process] = None
        self._auto_mock_popen: Optional[Popen] = None
        self._auto_server_popen: Optional[Popen] = None
        self._api_base: Optional[str] = None

    def get_server_process(self) -> Optional[Process]:
        """
        Get the neuro-san server process.

        :return: The process, or None before find_local_processes() or auto_start_servers(), or in remote mode
        """
        return self._server_process

    def get_mock_process(self) -> Optional[Process]:
        """
        Get the mock LLM server process.

        :return: The process, or None before find_local_processes() or auto_start_servers(), or in remote mode
        """
        return self._mock_process

    def get_api_base(self) -> Optional[str]:
        """
        Get the OPENAI_API_BASE that the neuro-san server uses.

        :return: The URL, or None when it is not known
        """
        return self._api_base

    def find_local_processes(self) -> None:
        """
        Locate neuro-san server and mock LLM server processes.
        Raises LoadTestAbortError if either is not found.
        Also validates the server's OPENAI_API_BASE matches the mock port.

        :raises LoadTestAbortError: With exit code 1 when a server process is missing or OPENAI_API_BASE does not match
        """
        self._server_process = ResourceMonitor.find_process("server_main_loop")
        self._mock_process = ResourceMonitor.find_process("mock_llm_server")

        default_mock_port: str = str(MockServerManager.DEFAULT_MOCK_PORT)
        default_api_base: str = MockServerManager._build_mock_api_base(default_mock_port)
        if self._server_process is None:
            MockServerManager.LOGGER.error(
                """neuro-san server process not found.
Start it with OPENAI_API_BASE pointing to the mock LLM server:
  export OPENAI_API_BASE=%s
  python -m neuro_san.service.main_loop.server_main_loop""",
                default_api_base,
            )
            raise LoadTestAbortError(1)
        MockServerManager.LOGGER.info("Found neuro-san server (PID %s)", self._server_process.pid)

        if self._mock_process is None:
            MockServerManager.LOGGER.error(
                """mock LLM server process not found.
Start the mock LLM server first, then the neuro-san server:
  python -m tests.mock_llm_server.mock_llm_server --port %s
Then:
  export OPENAI_API_BASE=%s
  python -m neuro_san.service.main_loop.server_main_loop""",
                MockServerManager.DEFAULT_MOCK_PORT, default_api_base,
            )
            raise LoadTestAbortError(1)
        MockServerManager.LOGGER.info("Found mock LLM server (PID %s)", self._mock_process.pid)

        mock_port: str = self._get_mock_server_port()
        self._api_base = self._check_server_api_base(mock_port)

    def auto_start_servers(self) -> None:
        """
        Start mock LLM and neuro-san servers as managed subprocesses.

        :raises LoadTestAbortError: With exit code 1 when either server exits during startup
        """
        mock_port: str = str(self._args.mock_port)
        api_base: str = MockServerManager._build_mock_api_base(mock_port)

        MockServerManager.LOGGER.info("Auto-starting mock LLM server (log: %s)", MockServerManager.MOCK_LOG_PATH)
        # The child process gets its own copy of the file descriptor, so this method can close the file
        # once Popen returns, and the server keeps writing to the log.
        with open(MockServerManager.MOCK_LOG_PATH, "w", encoding="utf-8") as mock_log_file:
            self._auto_mock_popen = Popen(  # pylint: disable=consider-using-with
                ["python", "-m", "tests.mock_llm_server.mock_llm_server",
                 "--port", mock_port],
                stdout=mock_log_file,
                stderr=mock_log_file,
            )

        # The overlay keeps openai-class models on Chat Completions, the only endpoint the mock serves.
        server_env: Dict[str, str] = environ.copy()
        server_env["OPENAI_API_BASE"] = api_base
        server_env["AGENT_LLM_INFO_FILE"] = MockServerManager.CHAT_COMPLETIONS_LLM_INFO_PATH
        MockServerManager.LOGGER.info("Auto-starting neuro-san server (log: %s)", MockServerManager.SERVER_LOG_PATH)
        with open(MockServerManager.SERVER_LOG_PATH, "w", encoding="utf-8") as server_log_file:
            self._auto_server_popen = Popen(  # pylint: disable=consider-using-with
                ["python", "-m", "neuro_san.service.main_loop.server_main_loop"],
                stdout=server_log_file,
                stderr=server_log_file,
                env=server_env,
            )

        MockServerManager.LOGGER.info("Waiting %ss for servers to start...", MockServerManager.STARTUP_WAIT_SECONDS)
        sleep(MockServerManager.STARTUP_WAIT_SECONDS)

        if self._auto_mock_popen.poll() is not None:
            MockServerManager.LOGGER.error("Mock LLM server exited unexpectedly. Check %s",
                                           MockServerManager.MOCK_LOG_PATH)
            raise LoadTestAbortError(1)

        if self._auto_server_popen.poll() is not None:
            MockServerManager.LOGGER.error("Neuro-san server exited unexpectedly. Check %s",
                                           MockServerManager.SERVER_LOG_PATH)
            self._auto_mock_popen.terminate()
            raise LoadTestAbortError(1)

        self._mock_process = Process(self._auto_mock_popen.pid)
        self._server_process = Process(self._auto_server_popen.pid)

        self._api_base = api_base
        MockServerManager.LOGGER.info("Mock LLM server ready (PID %s)", self._mock_process.pid)
        MockServerManager.LOGGER.info("Neuro-san server ready (PID %s)", self._server_process.pid)
        MockServerManager.LOGGER.info("  OPENAI_API_BASE=%s", self._api_base)
        MockServerManager.LOGGER.info("  AGENT_LLM_INFO_FILE=%s", MockServerManager.CHAT_COMPLETIONS_LLM_INFO_PATH)

    def stop_servers(self) -> None:
        """
        Terminate auto-started servers.
        """
        if self._auto_server_popen is not None:
            MockServerManager.LOGGER.info("Stopping neuro-san server (PID %s)...", self._auto_server_popen.pid)
            self._auto_server_popen.terminate()
            self._auto_server_popen.wait(timeout=MockServerManager.PROCESS_WAIT_TIMEOUT_SECONDS)
        if self._auto_mock_popen is not None:
            MockServerManager.LOGGER.info("Stopping mock LLM server (PID %s)...", self._auto_mock_popen.pid)
            self._auto_mock_popen.terminate()
            self._auto_mock_popen.wait(timeout=MockServerManager.PROCESS_WAIT_TIMEOUT_SECONDS)
        MockServerManager.LOGGER.info("Servers stopped.")

    def _get_mock_server_port(self) -> str:
        """
        Extract the --port value from the mock LLM server's command line.

        :return: The --port value, or DEFAULT_MOCK_PORT as a string if the command line has none or cannot be read
        """
        cmdline: List[str] = []
        try:
            cmdline = self._mock_process.cmdline()
            index: int
            arg: str
            # Find "--port" and return the command line item after it.
            for index, arg in enumerate(cmdline):
                if arg == "--port" and index + 1 < len(cmdline):
                    return cmdline[index + 1]
        except (NoSuchProcess, AccessDenied) as error:
            MockServerManager._log_process_read_error(DEBUG, "Could not read mock process cmdline", error)
        return str(MockServerManager.DEFAULT_MOCK_PORT)

    def _check_server_api_base(self, mock_port: str) -> Optional[str]:
        """
        Verify that the neuro-san server has OPENAI_API_BASE set and
        that it points to the correct mock LLM server port.
        Raises LoadTestAbortError if not set or mismatched.

        :param mock_port: Port the mock LLM server listens on
        :return: The server's OPENAI_API_BASE value, or None if its environment cannot be read
        :raises LoadTestAbortError: With exit code 1 when OPENAI_API_BASE is not set or does not reference mock_port
        """
        expected_url: str = MockServerManager._build_mock_api_base(mock_port)
        server_env: Dict[str, str] = {}
        try:
            server_env = self._server_process.environ()
        except (NoSuchProcess, AccessDenied) as error:
            MockServerManager._log_process_read_error(INFO, "Could not read server environment", error)
            return None

        api_base: Optional[str] = server_env.get("OPENAI_API_BASE")
        if api_base is None:
            MockServerManager.LOGGER.error(
                """neuro-san server does not have OPENAI_API_BASE set.
  Mock LLM server is running on port %s.
  Restart the server with:
    export OPENAI_API_BASE=%s
    python -m neuro_san.service.main_loop.server_main_loop""",
                mock_port, expected_url,
            )
            raise LoadTestAbortError(1)

        MockServerManager.LOGGER.info("  OPENAI_API_BASE=%s", api_base)

        # Without the overlay, model-name-only openai configs (math_guy, hello_world) use the
        # Responses API, which the mock does not serve, and every request is a 404. Warn rather
        # than exit: a deployment may pin Chat Completions through a per-network llm_info_file.
        # An empty value counts as unset: the shipped Dockerfiles define AGENT_LLM_INFO_FILE=""
        # and DefaultLlmFactory ignores an empty path just like a missing variable.
        llm_info_file: Optional[str] = server_env.get("AGENT_LLM_INFO_FILE")
        if not llm_info_file:
            MockServerManager.LOGGER.warning(
                """neuro-san server does not have AGENT_LLM_INFO_FILE set.
  The openai class defaults to the Responses API, which the mock LLM server does not
  serve, so model-name-only agent configs will get HTTP 404 from /v1/responses.
  Restart the server with:
    export AGENT_LLM_INFO_FILE=%s
    export OPENAI_API_BASE=%s
    python -m neuro_san.service.main_loop.server_main_loop""",
                MockServerManager.CHAT_COMPLETIONS_LLM_INFO_PATH, expected_url,
            )

        if mock_port not in api_base:
            MockServerManager.LOGGER.error(
                """OPENAI_API_BASE does not reference port %s.
  Mock LLM server is running on port %s,
  but OPENAI_API_BASE=%s
  Restart the server with:
    export OPENAI_API_BASE=%s
    python -m neuro_san.service.main_loop.server_main_loop""",
                mock_port, mock_port, api_base, expected_url,
            )
            raise LoadTestAbortError(1)
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
        sensitive_logger: SensitiveLogger = SensitiveLogger(MockServerManager.LOGGER)
        if sensitive_logger.should_log():
            sensitive_logger.log(level, "%s: %s", message, error)
        else:
            MockServerManager.LOGGER.log(level, "%s", message)

    @staticmethod
    def _build_mock_api_base(mock_port: str) -> str:
        """
        Build the OPENAI_API_BASE URL of the local mock LLM server.

        :param mock_port: Port the mock LLM server listens on
        :return: The URL, for example "http://localhost:8888/v1"
        """
        api_base: str = f"http://{MockServerManager.LOCALHOST}:{mock_port}/v1"
        return api_base
