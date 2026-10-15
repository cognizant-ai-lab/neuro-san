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

import logging
import os
import socket
from argparse import Namespace
from typing import Optional

import psutil

from tests.load_tests.config import SOCKET_CHECK_TIMEOUT
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError

logger: logging.Logger = logging.getLogger(__name__)


class EnvironmentValidator:
    """
    Validates the runtime environment for real-LLM load testing.

    Ensures that no mock_llm_server process is running, so the test
    makes real LLM calls.  Also checks that the target server
    is reachable on the given host/port, locates the neuro-san server
    process for resource monitoring, and finds its server log.
    """

    @staticmethod
    def validate_environment() -> None:
        """
        Validate that no mock_llm_server process is running.

        API key checks are intentionally omitted — the load test
        client communicates with the server over HTTP, so API keys
        are only needed on the server side.  Server-side key errors
        are caught at runtime via failure_patterns in the agent
        profile.
        """
        EnvironmentValidator._check_no_mock_environment()

    @staticmethod
    def is_port_open(host: str, port: int) -> bool:
        """
        Check if a TCP port is accepting connections.

        :param host: Server host name or address
        :param port: TCP port to check
        :return: True if a connection succeeds within SOCKET_CHECK_TIMEOUT, False otherwise
        """
        try:
            with socket.create_connection((host, port), timeout=SOCKET_CHECK_TIMEOUT):
                return True
        except (ConnectionRefusedError, OSError):
            return False

    @staticmethod
    def find_local_server(args: Namespace) -> Optional[psutil.Process]:
        """
        Locate the neuro-san server process for resource monitoring.

        Searches by process keyword first, then falls back to port
        ownership.

        :param args: Parsed arguments; host and port are used
        :return: The server process, or None when it is not found locally
        """
        if not EnvironmentValidator.is_port_open(args.host, args.port):
            logger.error("No service listening on %s:%s.\nStart the server first.", args.host, args.port)
            raise LoadTestAbortError(1)

        server_process: Optional[psutil.Process] = None
        keyword: str
        # Try each server process name until one is found.
        for keyword in ["neuro_san_studio", "server_main_loop"]:
            server_process = ResourceMonitor.find_process(keyword)
            if server_process is not None:
                logger.info("Found neuro-san server (PID %s) via %s", server_process.pid, keyword)
                break

        if server_process is None:
            server_process = ResourceMonitor.find_process_by_port(args.port)
            if server_process is not None:
                logger.info("Found neuro-san server (PID %s) via port %s", server_process.pid, args.port)

        if server_process is None:
            logger.info("neuro-san server process not found locally. Resource monitoring disabled.")
            return None

        return server_process

    @staticmethod
    def try_auto_detect_server_log(args: Namespace) -> Optional[str]:
        """
        Best-effort local server-log detection; None if unavailable.

        Unlike auto_detect_server_log, this never aborts.  It is used
        for the default (unrequested) auto-detect so that remote or
        no-server runs degrade quietly to no server-log analysis
        instead of failing.

        :param args: Parsed arguments; host and port are used
        :return: Path to logs/server.log in the server's working directory, or None when it cannot be found
        """
        if not EnvironmentValidator.is_port_open(args.host, args.port):
            return None
        server_process: Optional[psutil.Process] = None
        keyword: str
        # Try each server process name until one is found.
        for keyword in ["neuro_san_studio", "server_main_loop"]:
            server_process = ResourceMonitor.find_process(keyword)
            if server_process is not None:
                break
        if server_process is None:
            server_process = ResourceMonitor.find_process_by_port(args.port)
        if server_process is None:
            return None
        try:
            server_log_path: str = os.path.join(server_process.cwd(), "logs", "server.log")
            if os.path.isfile(server_log_path):
                return server_log_path
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            return None
        return None

    @staticmethod
    def auto_detect_server_log(server_process: Optional[psutil.Process]) -> str:
        """
        Auto-detect server log from server process CWD.

        Looks for logs/server.log relative to the server's working
        directory.  Raises LoadTestAbortError when auto-detection
        fails because the user explicitly requested --server-log.

        :param server_process: Local server process, or None when it was not found
        :return: Path to logs/server.log in the server's working directory
        """
        if server_process is None:
            logger.error("Cannot auto-detect server log: server process not found.")
            raise LoadTestAbortError(1)
        try:
            working_directory: str = server_process.cwd()
            server_log_path: str = os.path.join(working_directory, "logs", "server.log")
            if os.path.isfile(server_log_path):
                logger.info("  Auto-detected server log: %s", server_log_path)
                return server_log_path
            logger.error(
                """Server log not found at %s
  Provide the path explicitly: --server-log /path/to/server.log""",
                server_log_path,
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            logger.error(
                """Could not determine server working directory.
  Provide the path explicitly: --server-log /path/to/server.log""",
            )
        raise LoadTestAbortError(1)

    @staticmethod
    def _check_no_mock_environment() -> None:
        """
        Stop the run if a mock_llm_server process is running.

        OPENAI_API_BASE on its own does not mean the mock is in use: it is also
        how openai-class models reach LiteLLM or another OpenAI-compatible
        gateway, so it is only logged.
        """
        api_base: Optional[str] = os.environ.get("OPENAI_API_BASE")
        if api_base:
            logger.info("OPENAI_API_BASE is set: %s", api_base)
        mock_server_process: Optional[psutil.Process] = ResourceMonitor.find_process("mock_llm_server")
        if mock_server_process is not None:
            logger.error(
                "mock_llm_server is running (PID %s): stop it, or use load_test_mock_llm_service.py instead.",
                mock_server_process.pid,
            )
            raise LoadTestAbortError(1)
        logger.info("No mock LLM environment detected.")
