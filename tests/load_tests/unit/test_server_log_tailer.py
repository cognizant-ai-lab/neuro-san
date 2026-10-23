
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
# re.compile stays module-qualified: a specific import would hide the builtin compile.
import re
from argparse import Namespace
from os.path import join
from shutil import rmtree
from tempfile import mkdtemp
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase

from typing_extensions import override

from tests.load_tests.monitoring.server_log_tailer import ServerLogTailer


class TestServerLogTailer(TestCase):
    """
    Unit tests for ServerLogTailer: following a real server log file, and the duration filter.
    """

    # Lines that match the primary agent's Start and Finish patterns in _tail().
    START_LINE: str = "primary Start\n"
    FINISH_LINE: str = "primary Finish\n"

    @override
    def setUp(self) -> None:
        """
        Make a scratch directory for the server log.
        """
        self._dir: str = mkdtemp()
        self._log_path: str = join(self._dir, "server.log")

    @override
    def tearDown(self) -> None:
        """
        Remove the scratch directory.
        """
        rmtree(self._dir, ignore_errors=True)

    def test_tail_counts_starts_and_finishes(self) -> None:
        """
        Two Start and two Finish lines finish the round with both requests received and processed.
        """
        start_line: str = TestServerLogTailer.START_LINE
        finish_line: str = TestServerLogTailer.FINISH_LINE
        self._write_log([start_line, "other line\n", start_line, finish_line, finish_line])
        tail_result: Dict[str, Any] = self._tail(expected_count=2, stage_timeout_seconds=30)
        received_count: int = tail_result.get("count")
        completed_count: int = tail_result.get("completed")
        interrupted: bool = tail_result.get("interrupted")
        peak_system_memory_percent: float = tail_result.get("peak_sys_mem_pct")
        peak_server: Optional[Dict[str, Any]] = tail_result.get("peak_server")
        self.assertEqual(received_count, 2)
        self.assertEqual(completed_count, 2)
        self.assertFalse(interrupted)
        self.assertGreaterEqual(peak_system_memory_percent, 10.0)
        self.assertIsNone(peak_server)

    def test_tail_stops_at_stage_timeout(self) -> None:
        """
        With fewer Start lines than expected, the round stops at the stage timeout and logs a warning.
        """
        self._write_log([TestServerLogTailer.START_LINE])
        with self.assertLogs("tests.load_tests.monitoring.server_log_tailer", level="WARNING") as captured:
            tail_result: Dict[str, Any] = self._tail(expected_count=3, stage_timeout_seconds=0)
        warning_text: str = captured.output[0]
        received_count: int = tail_result.get("count")
        completed_count: int = tail_result.get("completed")
        elapsed_seconds: float = tail_result.get("elapsed_seconds")
        self.assertEqual(received_count, 1)
        self.assertEqual(completed_count, 0)
        self.assertGreater(elapsed_seconds, 0.0)
        self.assertIn("Stage timeout (0s) reached with 1/3 requests received.", warning_text)

    def test_tail_finishes_when_completions_outrun_starts(self) -> None:
        """
        Finish lines without Start lines (the monitor started late) still finish the round at the expected count.
        """
        self._write_log([TestServerLogTailer.FINISH_LINE, TestServerLogTailer.FINISH_LINE])
        tail_result: Dict[str, Any] = self._tail(expected_count=2, stage_timeout_seconds=30)
        received_count: int = tail_result.get("count")
        completed_count: int = tail_result.get("completed")
        self.assertEqual(received_count, 0)
        self.assertEqual(completed_count, 2)

    def test_positive_durations_keeps_numbers_above_zero(self) -> None:
        """
        Only durations that are numbers above 0 are kept, in pair order.
        """
        pairs: List[Dict[str, Any]] = [
            {"duration_seconds": 1.5}, {"duration_seconds": 0}, {"duration_seconds": None},
            {}, {"duration_seconds": 2},
        ]
        durations_seconds: List[float] = ServerLogTailer.positive_durations(pairs)
        self.assertEqual(durations_seconds, [1.5, 2])

    def _write_log(self, lines: List[str]) -> None:
        """
        Write the scratch server log.

        :param lines: The log lines, each ending with a newline
        """
        with open(self._log_path, "w", encoding="utf-8") as log_file:
            log_file.writelines(lines)

    def _tail(self, expected_count: int, stage_timeout_seconds: float) -> Dict[str, Any]:
        """
        Tail the scratch server log from its start, with no server process and no log monitor.

        :param expected_count: Number of requests to wait for
        :param stage_timeout_seconds: The --stage-timeout value
        :return: The tail result
        """
        args: Namespace = Namespace(server_log=self._log_path, stage_timeout=stage_timeout_seconds)
        server_log_tailer: ServerLogTailer = ServerLogTailer(args, None, None)
        round_values: Dict[str, Any] = {
            "expected": expected_count,
            "log_position": 0,
            "primary_start_regex": re.compile("primary Start"),
            "primary_finish_regex": re.compile("primary Finish"),
            "before_server": None,
            "before_system_memory_percent": 10.0,
        }
        tail_result: Dict[str, Any] = server_log_tailer.tail_server_log(round_values)
        return tail_result
