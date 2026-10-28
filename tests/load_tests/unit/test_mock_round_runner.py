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
from os import environ
from subprocess import CompletedProcess
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor
from typing_extensions import override

from tests.load_tests.mock_service.mock_round_runner import MockRoundRunner


class TestMockRoundRunner(TestCase):
    """
    Unit tests for MockRoundRunner: the stderr line logged for a failed request in a one-request round.
    """

    RUN_TARGET: str = "tests.load_tests.mock_service.mock_round_runner.run"

    @override
    def setUp(self) -> None:
        """
        Build a runner whose agent_cli request fails with a secret on its last stderr line.
        """
        round_settings: Dict[str, Any] = {
            "num_rounds": 1,
            "num_requests": 1,
            "max_workers": 1,
            "settle_time_seconds": 0,
            "host": "localhost",
            "port": 8080,
            "agent": "hello_world",
            "no_sly_data": True,
            "sly_data": None,
        }
        # No server processes, so the round takes no resource snapshots.
        server_manager: MagicMock = MagicMock()
        server_manager.get_server_process.return_value = None
        server_manager.get_mock_process.return_value = None
        self.runner: MockRoundRunner = MockRoundRunner(round_settings, "prompt.txt", server_manager)
        failed_result: CompletedProcess = CompletedProcess([], 1, "", "Traceback\nValueError: key sk-secret\n")
        run_patch: Any = patch(TestMockRoundRunner.RUN_TARGET, return_value=failed_result)
        run_patch.start()
        self.addCleanup(run_patch.stop)

    def test_failed_request_shows_stderr_line(self) -> None:
        """
        With LEAF_LOG_SENSITIVE=true the last stderr line is logged under the FAIL line.
        """
        sensitive_setting: Dict[str, str] = {"LEAF_LOG_SENSITIVE": "true"}
        with patch.dict(environ, sensitive_setting), self.assertLogs("MockRoundRunner", level="INFO") as captured:
            rounds_result: Dict[str, Any] = self.runner.run_rounds()
        failed_count: float = DictionaryExtractor(rounds_result).get("totals.failed")
        stderr_lines: List[str] = TestMockRoundRunner._stderr_lines(captured.output)
        self.assertEqual(failed_count, 1)
        self.assertEqual(stderr_lines, ["INFO:MockRoundRunner:  stderr: ValueError: key sk-secret"])

    def test_failed_request_hides_stderr_line(self) -> None:
        """
        With LEAF_LOG_SENSITIVE=false the stderr text is dropped and a plain line says how to show it.
        """
        sensitive_setting: Dict[str, str] = {"LEAF_LOG_SENSITIVE": "false"}
        with patch.dict(environ, sensitive_setting), self.assertLogs("MockRoundRunner", level="INFO") as captured:
            self.runner.run_rounds()
        stderr_lines: List[str] = TestMockRoundRunner._stderr_lines(captured.output)
        expected_line: str = "INFO:MockRoundRunner:  stderr: (hidden; set LEAF_LOG_SENSITIVE=true to show it)"
        self.assertEqual(stderr_lines, [expected_line])

    @staticmethod
    def _stderr_lines(log_lines: List[str]) -> List[str]:
        """
        Keep only the stderr lines from captured log output.

        :param log_lines: Captured log lines, e.g. "INFO:MockRoundRunner:Request 1: FAIL (0.1s)"
        :return: The lines that show the stderr of a failed request
        """
        stderr_lines: List[str] = []
        line: str
        # Keep each captured line that shows a request's stderr, in log order.
        for line in log_lines:
            if line.startswith("INFO:MockRoundRunner:  stderr:"):
                stderr_lines.append(line)
        return stderr_lines
