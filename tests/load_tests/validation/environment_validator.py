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

"""Pre-flight environment checks for real-LLM load testing.

Validates that the runtime environment is configured for real LLM calls:
  - No mock LLM server or OPENAI_API_BASE override detected
  - Target server must be reachable on the specified host/port
  - Auto-detects server log from process CWD when requested

API key validation is intentionally omitted because the load test
communicates with the server over HTTP — API keys are only needed
on the server side.  Server-side key errors are caught at runtime
by the failure_patterns mechanism in agent profiles.
"""

import logging
import os
import socket
import sys
from typing import Optional

import psutil

from tests.load_tests.config import SOCKET_CHECK_TIMEOUT
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor

logger = logging.getLogger(__name__)


class EnvironmentValidator:
    """Validates the runtime environment for load testing.

    Ensures that real LLM infrastructure is in place and no mock
    environment is accidentally active.  Also locates the neuro-san
    server process for resource monitoring.
    """

    @staticmethod
    def validate_environment() -> None:
        """Validate that no mock LLM environment is active.

        API key checks are intentionally omitted — the load test
        client communicates with the server over HTTP, so API keys
        are only needed on the server side.  Server-side key errors
        are caught at runtime via failure_patterns in the agent
        profile.
        """
        EnvironmentValidator._check_no_mock_environment()

    @staticmethod
    def _check_no_mock_environment() -> None:
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
            with socket.create_connection(
                (host, port), timeout=SOCKET_CHECK_TIMEOUT,
            ):
                return True
        except (ConnectionRefusedError, OSError):
            return False

    @staticmethod
    def find_local_server(args) -> Optional[psutil.Process]:
        """Locate the neuro-san server process for resource monitoring.

        Searches by process keyword first, then falls back to port
        ownership.  Returns the process or None.
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
            return None

        return server_proc

    @staticmethod
    def auto_detect_server_log(server_proc) -> str:
        """Auto-detect server log from server process CWD.

        Looks for logs/server.log relative to the server's working
        directory.  Aborts with sys.exit(1) when auto-detection
        fails because the user explicitly requested --server-log.
        """
        if server_proc is None:
            logger.error(
                "Cannot auto-detect server log: "
                "server process not found.",
            )
            sys.exit(1)
        try:
            cwd = server_proc.cwd()
            candidate = os.path.join(cwd, "logs", "server.log")
            if os.path.isfile(candidate):
                logger.info(
                    "  Auto-detected server log: %s", candidate,
                )
                return candidate
            logger.error(
                "Server log not found at %s\n"
                "  Provide the path explicitly: "
                "--server-log /path/to/server.log",
                candidate,
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            logger.error(
                "Could not determine server working directory.\n"
                "  Provide the path explicitly: "
                "--server-log /path/to/server.log",
            )
        sys.exit(1)
