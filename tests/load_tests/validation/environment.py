"""Environment validation — server discovery, port checks, and mock detection."""

import logging
import os
import socket
import sys

from tests.load_tests.monitoring.resource_monitor import ResourceMonitor

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
            server_proc = ResourceMonitor.find_process_by_port(args.port)
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
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning(
                "  Could not determine server working directory. "
                "Retry monitoring unavailable.",
            )
        return None
