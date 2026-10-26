
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
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.traffic.stage_executor import StageExecutor


class TestStageExecutor(TestCase):
    """
    Unit tests for StageExecutor: the --total-timeout stop.
    """

    def test_total_timeout_line_prints_minutes_and_seconds(self) -> None:
        """
        A test past --total-timeout reports the timeout and logs the time taken as minutes and seconds.
        """
        args: Namespace = Namespace(num_rounds=1, total_timeout=900)
        stage_executor: StageExecutor = StageExecutor(args, None, {})
        timeout_reached: bool = False
        # The fake clock reads 1205 seconds after a test start at 0.
        with patch("tests.load_tests.traffic.stage_executor.perf_counter", return_value=1205.0):
            with self.assertLogs(stage_executor.logger, level="WARNING") as captured:
                timeout_reached = stage_executor.total_timeout_reached(0.0)
        log_text: str = "\n".join(captured.output)
        self.assertTrue(timeout_reached)
        self.assertIn("--total-timeout (900s) reached after 20m 5s", log_text)

    def test_no_total_timeout_when_disabled(self) -> None:
        """
        --total-timeout 0 never stops the test.
        """
        args: Namespace = Namespace(num_rounds=1, total_timeout=0)
        stage_executor: StageExecutor = StageExecutor(args, None, {})
        timeout_reached: bool = stage_executor.total_timeout_reached(0.0)
        self.assertFalse(timeout_reached)
