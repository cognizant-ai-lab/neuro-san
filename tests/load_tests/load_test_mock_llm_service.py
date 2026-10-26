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

from argparse import Namespace
from inspect import cleandoc
from logging import FileHandler
from logging import Formatter
from logging import INFO
from logging import Logger
from logging import basicConfig
from logging import getLogger
from os import remove
from os.path import exists
from time import strftime
from typing import Any
from typing import Dict
from typing import Optional

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.mock_service.leak_reporter import LeakReporter
from tests.load_tests.mock_service.mock_load_test_arguments import MockLoadTestArguments
from tests.load_tests.mock_service.mock_round_runner import MockRoundRunner
from tests.load_tests.mock_service.mock_server_manager import MockServerManager
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError


class MockLlmLoadTest:
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

    PROMPT_FILE_PATH: str = "/tmp/load_test_prompt.txt"

    def __init__(self, args: Namespace) -> None:
        """
        Initialize the load test with parsed command-line arguments.

        :param args: Parsed command-line arguments from MockLoadTestArguments.parse_args()
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.args: Namespace = args
        self._server_manager: MockServerManager = MockServerManager(args)
        prompt_file: str = MockLlmLoadTest.PROMPT_FILE_PATH
        self._round_runner: MockRoundRunner = MockRoundRunner(args, prompt_file, self._server_manager)
        self._leak_reporter: LeakReporter = LeakReporter(args)
        self._test_log_path: Optional[str] = None
        self._test_log_handler: Optional[FileHandler] = None

    @staticmethod
    def main() -> None:
        """
        Entry point for the load test script.

        :raises SystemExit: With code 1 when a check stops the run
        """
        basicConfig(level=INFO, format="%(message)s")
        # --help prints the class docstring (the usage examples) after the flags, without its indentation.
        usage_text: str = cleandoc(MockLlmLoadTest.__doc__)
        argument_parser: MockLoadTestArguments = MockLoadTestArguments(usage_text)
        try:
            MockLlmLoadTest._run_with_arguments(argument_parser)
        except LoadTestAbortError as abort_error:
            # The check that stopped the run has already logged what to fix.
            exit_code: int = abort_error.get_exit_code()
            raise SystemExit(exit_code) from abort_error

    def run(self) -> None:
        """
        Execute the full load test workflow.

        :raises LoadTestAbortError: With exit code 1 when --auto-start is used with a remote server,
            or when a server check fails
        """
        self._setup_test_log()

        with open(MockLlmLoadTest.PROMPT_FILE_PATH, "w", encoding="utf-8") as prompt_file_handle:
            prompt_file_handle.write(self.args.prompt)

        is_local: bool = self.args.host in LoadTestConstants.LOCAL_HOSTS

        if self.args.auto_start:
            if not is_local:
                self.logger.error("--auto-start can only be used with local mode (localhost).")
                raise LoadTestAbortError(1)
            self._server_manager.auto_start_servers()
        elif is_local:
            self._server_manager.find_local_processes()
        else:
            self.logger.info("Remote mode: targeting %s:%s", self.args.host, self.args.port)
            self.logger.info("  Process monitoring disabled (server is not local)")

        self.logger.info(
            "\nConfig: agent=%s, requests=%s, workers=%s, rounds=%s, host=%s, port=%s",
            self.args.agent, self.args.num_requests, self.args.max_workers,
            self.args.num_rounds, self.args.host, self.args.port,
        )
        if not self.args.no_sly_data:
            self.logger.info("  sly_data=%s", self.args.sly_data)
        self.logger.info("  prompt=\"%s\"", self.args.prompt)
        self.logger.info("  settle_time=%ss", self.args.settle_time_seconds)

        totals: Dict[str, float] = {
            "passed": 0,
            "failed": 0,
            "time_seconds": 0.0,
        }
        try:
            rounds_result: Dict[str, Any] = self._round_runner.run_rounds()
            totals = rounds_result.get("totals")
            self._leak_reporter.log_results(rounds_result)
            if is_local and not self.args.auto_start:
                self.logger.info("\n%s", Formatters.SEPARATOR_LINE)
                self.logger.info("  WARNING: ENVIRONMENT VARIABLE STILL ACTIVE ON NEURO-SAN SERVER")
                self.logger.info("  Key:   OPENAI_API_BASE")
                api_base: Optional[str] = self._server_manager.get_api_base()
                self.logger.info("  Value: %s", api_base)
                self.logger.info("  All agent requests are routed to the mock LLM server.")
                self.logger.info("  To restore normal operation:")
                self.logger.info("    1. Stop the neuro-san server")
                self.logger.info("    2. unset OPENAI_API_BASE")
                self.logger.info("    3. Restart: python -m neuro_san.service.main_loop.server_main_loop")
                self.logger.info("%s", Formatters.SEPARATOR_LINE)
        finally:
            if self.args.auto_start:
                self._server_manager.stop_servers()
            self._finalize_test_log(totals)

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

        :param totals: Totals from MockRoundRunner.run_rounds(); only "failed" is read
        """
        if self._test_log_handler is not None:
            root_logger: Logger = getLogger()
            root_logger.removeHandler(self._test_log_handler)
            self._test_log_handler.close()
        if self._test_log_path is None:
            return
        if totals.get("failed", 0) > 0:
            self.logger.info("\nTest log saved: %s", self._test_log_path)
        elif exists(self._test_log_path):
            remove(self._test_log_path)

    @staticmethod
    def _run_with_arguments(argument_parser: MockLoadTestArguments) -> None:
        """
        Parse the command line and run the load test.

        :param argument_parser: The argument parser of the mock load test
        :raises LoadTestAbortError: With exit code 1 when an argument or server check fails
        """
        args: Namespace = argument_parser.parse_args()
        load_test: MockLlmLoadTest = MockLlmLoadTest(args)
        load_test.run()


if __name__ == "__main__":
    MockLlmLoadTest.main()
