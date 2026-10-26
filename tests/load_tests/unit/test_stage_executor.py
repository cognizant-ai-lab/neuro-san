
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
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.traffic.stage_executor import StageExecutor


class TestStageExecutor(TestCase):
    """
    Unit tests for StageExecutor: the --total-timeout stop.
    """

    def test_total_timeout_line_prints_minutes_and_seconds(self) -> None:
        """
        A test past --total-timeout stops before its first stage and logs the time taken as minutes and seconds.
        """
        args: Namespace = Namespace(num_rounds=1, total_timeout=900)
        stage_executor: StageExecutor = StageExecutor(args, None, {})
        run_inputs: Dict[str, Any] = {
            "stages": [1],
            "total_cap": 5,
            "monitor_resources": False,
            "has_server_log": False,
            "probe_result": None,
        }
        # The fake clock starts the test at 0 and reads 1205 seconds before the first stage.
        clock_readings: List[float] = [0.0, 1205.0]
        stages_outcome: Dict[str, Any] = {}
        with patch("tests.load_tests.traffic.stage_executor.perf_counter", side_effect=clock_readings):
            with self.assertLogs(stage_executor.logger, level="WARNING") as captured:
                stages_outcome = stage_executor.run_all_stages(run_inputs)
        aborted: bool = stages_outcome.get("aborted")
        stage_summaries: List[Dict[str, Any]] = stages_outcome.get("stage_summaries")
        log_text: str = "\n".join(captured.output)
        self.assertTrue(aborted)
        self.assertEqual(stage_summaries, [])
        self.assertIn("--total-timeout (900s) reached after 20m 5s", log_text)
