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

import os
import socket
from logging import Logger
from logging import getLogger
from typing import Optional

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.process_read_error import ProcessReadError
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.tracked_process import TrackedProcess
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError


class EnvironmentValidator:
    """
    Validates the runtime environment for real-LLM load testing.

    Ensures that no mock_llm_server process is running, so the test
    makes real LLM calls.  Also checks that the target server
    is reachable on the given host/port, locates the neuro-san server
    process for resource monitoring, and finds its server log.
    """

    def __init__(self) -> None:
        """
        Set up the logger.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    def validate_environment(self) -> None:
        """
        Validate that no mock_llm_server process is running.

        API key checks are intentionally omitted — the load test
        client communicates with the server over HTTP, so API keys
        are only needed on the server side.  Server-side key errors
        are caught at runtime via failure_patterns in the agent
        profile.
        """
        self._check_no_mock_environment()

    @staticmethod
    def is_port_open(host: str, port: int) -> bool:
        """
        Check if a TCP port is accepting connections.

        :param host: Server host name or address
        :param port: TCP port to check
        :return: True if a connection succeeds within LoadTestConstants.SOCKET_CHECK_TIMEOUT_SECONDS,
            False otherwise
        """
        try:
            with socket.create_connection((host, port), timeout=LoadTestConstants.SOCKET_CHECK_TIMEOUT_SECONDS):
                return True
        except (ConnectionRefusedError, OSError):
            return False

    def find_local_server(self, host: str, port: int) -> Optional[TrackedProcess]:
        """
        Locate the neuro-san server process for resource monitoring.

        Searches by process keyword first, then falls back to port
        ownership.

        :param host: Server host name or address
        :param port: Server TCP port
        :return: The server process, or None when it is not found locally
        """
        if not EnvironmentValidator.is_port_open(host, port):
            self.logger.error("No service listening on %s:%s.\nStart the server first.", host, port)
            raise LoadTestAbortError(1)

        server_process: Optional[TrackedProcess] = None
        keyword: str
        # Try each server process name until one is found.
        for keyword in ["neuro_san_studio", "server_main_loop"]:
            server_process = ResourceMonitor.find_process(keyword)
            if server_process is not None:
                self.logger.info("Found neuro-san server (PID %s) via %s", server_process.get_pid(), keyword)
                break

        if server_process is None:
            server_process = ResourceMonitor.find_process_by_port(port)
            if server_process is not None:
                self.logger.info("Found neuro-san server (PID %s) via port %s", server_process.get_pid(), port)

        if server_process is None:
            self.logger.info("neuro-san server process not found locally. Resource monitoring disabled.")
            return None

        return server_process

    @staticmethod
    def try_auto_detect_server_log(host: str, port: int) -> Optional[str]:
        """
        Best-effort local server-log detection; None if unavailable.

        Unlike auto_detect_server_log, this never aborts.  It is used
        for the default (unrequested) auto-detect so that remote or
        no-server runs degrade quietly to no server-log analysis
        instead of failing.

        :param host: Server host name or address
        :param port: Server TCP port
        :return: Path to logs/server.log in the server's working directory, or None when it cannot be found
        """
        if not EnvironmentValidator.is_port_open(host, port):
            return None
        server_process: Optional[TrackedProcess] = None
        keyword: str
        # Try each server process name until one is found.
        for keyword in ["neuro_san_studio", "server_main_loop"]:
            server_process = ResourceMonitor.find_process(keyword)
            if server_process is not None:
                break
        if server_process is None:
            server_process = ResourceMonitor.find_process_by_port(port)
        if server_process is None:
            return None
        try:
            server_log_path: str = os.path.join(server_process.cwd(), "logs", "server.log")
            if os.path.isfile(server_log_path):
                return server_log_path
        except (ProcessReadError, OSError):
            return None
        return None

    def auto_detect_server_log(self, server_process: Optional[TrackedProcess]) -> str:
        """
        Auto-detect server log from server process CWD.

        Looks for logs/server.log relative to the server's working
        directory.  Raises LoadTestAbortError when auto-detection
        fails because the user explicitly requested --server-log.

        :param server_process: Local server process, or None when it was not found
        :return: Path to logs/server.log in the server's working directory
        """
        if server_process is None:
            self.logger.error("Cannot auto-detect server log: server process not found.")
            raise LoadTestAbortError(1)
        try:
            working_directory: str = server_process.cwd()
            server_log_path: str = os.path.join(working_directory, "logs", "server.log")
            if os.path.isfile(server_log_path):
                self.logger.info("  Auto-detected server log: %s", server_log_path)
                return server_log_path
            self.logger.error("""Server log not found at %s
  Provide the path explicitly: --server-log /path/to/server.log""", server_log_path)
        except (ProcessReadError, OSError):
            self.logger.error("""Could not determine server working directory.
  Provide the path explicitly: --server-log /path/to/server.log""")
        raise LoadTestAbortError(1)

    def _check_no_mock_environment(self) -> None:
        """
        Stop the run if a mock_llm_server process is running.

        OPENAI_API_BASE on its own does not mean the mock is in use: it is also
        how openai-class models reach LiteLLM or another OpenAI-compatible
        gateway, so it is only logged.
        """
        api_base: Optional[str] = os.environ.get("OPENAI_API_BASE")
        if api_base:
            self.logger.info("OPENAI_API_BASE is set: %s", api_base)
        mock_server_process: Optional[TrackedProcess] = ResourceMonitor.find_process("mock_llm_server")
        if mock_server_process is not None:
            mock_server_pid: int = mock_server_process.get_pid()
            self.logger.error(
                "mock_llm_server is running (PID %s): stop it, or use load_test_mock_llm_service.py instead.",
                mock_server_pid)
            raise LoadTestAbortError(1)
        self.logger.info("No mock LLM environment detected.")
