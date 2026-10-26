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
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from logging import Logger
from logging import getLogger
from subprocess import CompletedProcess
from subprocess import run
from time import perf_counter
from time import sleep
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from psutil import Process

from tests.load_tests.mock_service.mock_server_manager import MockServerManager
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.reporting.formatters import Formatters


class MockRoundRunner:
    """
    Runs the rounds of the mock LLM load test.

    Each round fires num_requests concurrent agent_cli requests, waits for the server to settle,
    and builds a resource row for each server from snapshots taken before and after the round.
    """

    LOGGER: Logger = getLogger(__name__)

    MOCK_REQUEST_TIMEOUT_SECONDS: int = 120

    def __init__(self, args: Namespace, prompt_file: str, server_manager: MockServerManager) -> None:
        """
        Initialize the runner and build its agent_cli command.

        :param args: Parsed command-line arguments from MockLoadTestArguments.parse_args()
        :param prompt_file: Path of the file that holds the prompt for --first_prompt_file
        :param server_manager: Holds the server processes to take snapshots of
        """
        self._args: Namespace = args
        self._prompt_file: str = prompt_file
        self._server_manager: MockServerManager = server_manager
        self._agent_cli_command: List[str] = self._build_cli_command()

    def run_rounds(self) -> Dict[str, Any]:
        """
        Execute all rounds of the load test, collecting snapshots
        and results per round.

        :return: "server_rows" and "mock_rows" (rows from _build_snapshot_row()), and "totals"
                 with "passed", "failed" and "time_seconds"
        """
        server_rows: List[Dict[str, Any]] = []
        mock_rows: List[Dict[str, Any]] = []
        totals: Dict[str, float] = {
            "passed": 0,
            "failed": 0,
            "time_seconds": 0.0,
        }
        round_result: Dict[str, Any] = {}

        round_number: int
        # Run each round, numbered from 1, with resource snapshots before and after it.
        for round_number in range(1, self._args.num_rounds + 1):
            MockRoundRunner.LOGGER.info("\n%s", Formatters.SEPARATOR_LINE)
            MockRoundRunner.LOGGER.info(
                "  ROUND %s of %s (%s requests, %s workers)",
                round_number, self._args.num_rounds,
                self._args.num_requests, self._args.max_workers,
            )
            MockRoundRunner.LOGGER.info("%s", Formatters.SEPARATOR_LINE)

            server_process: Optional[Process] = self._server_manager.get_server_process()
            mock_process: Optional[Process] = self._server_manager.get_mock_process()
            before_server: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(server_process)
            before_mock: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(mock_process)
            if before_server:
                ResourceMonitor.log_snapshot("Server BEFORE", before_server)

            MockRoundRunner.LOGGER.info(
                "\nFiring %s concurrent requests with %s workers...",
                self._args.num_requests, self._args.max_workers,
            )
            round_result = self._run_round()
            # Plain key assignments: 3 more locals would pass pylint's 15-local limit (R0914).
            totals["passed"] = totals.get("passed", 0) + round_result.get("passed")
            totals["failed"] = totals.get("failed", 0) + round_result.get("failed")
            totals["time_seconds"] = totals.get("time_seconds", 0.0) + round_result.get("round_seconds")

            MockRoundRunner.LOGGER.info("\nWaiting %ss for server cleanup...", self._args.settle_time_seconds)
            sleep(self._args.settle_time_seconds)

            after_server: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(server_process)
            after_mock: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(mock_process)
            if after_server:
                ResourceMonitor.log_snapshot("Server AFTER", after_server)

            if before_server and after_server:
                server_row: Dict[str, Any] = MockRoundRunner._build_snapshot_row(round_number, before_server,
                                                                                 after_server)
                server_rows.append(server_row)
            if before_mock and after_mock:
                mock_row: Dict[str, Any] = MockRoundRunner._build_snapshot_row(round_number, before_mock, after_mock)
                mock_rows.append(mock_row)

        rounds_result: Dict[str, Any] = {
            "server_rows": server_rows,
            "mock_rows": mock_rows,
            "totals": totals,
        }
        return rounds_result

    def _build_cli_command(self) -> List[str]:
        """
        Build the agent_cli subprocess command list from instance arguments.
        Includes --no_thinking_file to avoid race conditions under concurrency.

        :return: The agent_cli command and its arguments, one list item each
        """
        agent_cli_command: List[str] = [
            "python", "-m", "neuro_san.client.agent_cli",
            "--http",
            "--host", self._args.host,
            "--port", str(self._args.port),
            "--agent", self._args.agent,
            "--first_prompt_file", self._prompt_file,
            "--one_shot",
            "--no_thinking_file",
        ]
        if not self._args.no_sly_data:
            agent_cli_command.extend(["--sly_data", self._args.sly_data])
        return agent_cli_command

    def _run_one(self, request_id: int) -> Dict[str, Any]:
        """
        Execute a single agent_cli request and return timing + status.
        Runs on a pool thread; it only reads the agent_cli command, which no thread changes.

        :param request_id: Number of the request in its round, starting at 1
        :return: "ok" (bool, exit code 0) and "elapsed_seconds" (float)
        """
        start_seconds: float = perf_counter()
        result: CompletedProcess = run(self._agent_cli_command, capture_output=True, text=True,
                                       timeout=MockRoundRunner.MOCK_REQUEST_TIMEOUT_SECONDS, check=False)
        elapsed_seconds: float = perf_counter() - start_seconds
        succeeded: bool = result.returncode == 0
        status: str = "FAIL"
        if succeeded:
            status = "OK"
        MockRoundRunner.LOGGER.info("Request %s: %s (%.2fs)", request_id, status, elapsed_seconds)
        if not succeeded:
            # Show last line of stderr for quick diagnosis
            stderr_text: str = result.stderr or ""
            stripped_stderr: str = stderr_text.strip()
            stderr_lines: List[str] = stripped_stderr.split("\n")
            stderr_line: str = stderr_lines[-1]
            MockRoundRunner.LOGGER.info("  stderr: %s", stderr_line)
        request_result: Dict[str, Any] = {
            "ok": succeeded,
            "elapsed_seconds": elapsed_seconds,
        }
        return request_result

    def _run_round(self) -> Dict[str, Any]:
        """
        Fire num_requests concurrent requests using a thread pool.

        :return: "passed" and "failed" (request counts) and "round_seconds" (the round time)
        """
        passed: int = 0
        failed: int = 0
        start_seconds: float = perf_counter()
        with ThreadPoolExecutor(max_workers=self._args.max_workers) as pool:
            futures: List[Future] = []
            request_id: int
            # Submit every request first, numbered from 1, so the requests run at the same time.
            for request_id in range(1, self._args.num_requests + 1):
                request_future: Future = pool.submit(self._run_one, request_id)
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
        MockRoundRunner.LOGGER.info("\nResult: %s passed, %s failed in %.2fs", passed, failed, round_seconds)
        round_result: Dict[str, Any] = {
            "passed": passed,
            "failed": failed,
            "round_seconds": round_seconds,
        }
        return round_result

    @staticmethod
    def _build_snapshot_row(round_number: int, before_snapshot: Dict[str, Any],
                            after_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build one round's resource numbers from before/after snapshots.

        :param round_number: Round number, starting at 1
        :param before_snapshot: ResourceMonitor.snapshot() taken before the round
        :param after_snapshot: ResourceMonitor.snapshot() taken after the round settled
        :return: "round_number", "before_rss_megabytes", "settled_rss_megabytes", "rss_delta_megabytes", "fds",
                 "before_threads", "settled_threads", "thread_delta", "connections", "cpu_percent" and "children"
        """
        rss_delta_megabytes: float = after_snapshot.get("rss_megabytes") - before_snapshot.get("rss_megabytes")
        thread_delta: int = after_snapshot.get("threads") - before_snapshot.get("threads")
        snapshot_row: Dict[str, Any] = {
            "round_number": round_number,
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
