
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
from unittest.mock import MagicMock
from unittest.mock import _Call

from tests.load_tests.traffic.stage_run import StageRun


class TestStageRun(TestCase):
    """
    Unit tests for StageRun: the --max-requests cap, the --total-timeout stop, the stage abort and the probe
    result in the first stage only.
    """

    def test_request_cap_stops_the_next_round(self) -> None:
        """
        With stages 2,2, two rounds and --max-requests 3, the second stage sends 1 request and round 2 stops
        at the cap with the warning.
        """
        stage_executor: MagicMock = self._stage_executor(timeout_reached=False, should_abort=False)
        args: Namespace = Namespace(num_rounds=2)
        run_inputs: Dict[str, Any] = self._run_inputs([2, 2], 3)
        stage_run: StageRun = StageRun(args, stage_executor, run_inputs)
        stages_outcome: Dict[str, Any] = {}
        with self.assertLogs(stage_run.logger, level="WARNING") as captured:
            stages_outcome = stage_run.run()
        actual_requests: List[Any] = self._stage_input_values(stage_executor, "actual_requests")
        stage_summaries: List[Dict[str, Any]] = stages_outcome.get("stage_summaries")
        stage_count: int = len(stage_summaries)
        aborted: bool = stages_outcome.get("aborted")
        log_text: str = "\n".join(captured.output)
        self.assertEqual(actual_requests, [2, 1])
        self.assertEqual(stage_count, 2)
        self.assertFalse(aborted)
        self.assertIn("Only 3 of 8 total planned requests completed", log_text)

    def test_total_timeout_aborts_before_a_stage(self) -> None:
        """
        When --total-timeout is reached, no stage runs and the run is aborted.
        """
        stage_executor: MagicMock = self._stage_executor(timeout_reached=True, should_abort=False)
        args: Namespace = Namespace(num_rounds=1)
        run_inputs: Dict[str, Any] = self._run_inputs([1], 5)
        stage_run: StageRun = StageRun(args, stage_executor, run_inputs)
        stages_outcome: Dict[str, Any] = stage_run.run()
        aborted: bool = stages_outcome.get("aborted")
        stage_summaries: List[Dict[str, Any]] = stages_outcome.get("stage_summaries")
        self.assertTrue(aborted)
        self.assertEqual(stage_summaries, [])
        stage_executor.run_single_stage.assert_not_called()

    def test_stage_abort_stops_the_run(self) -> None:
        """
        A stage that must abort the test stops the run after its summary is kept.
        """
        stage_executor: MagicMock = self._stage_executor(timeout_reached=False, should_abort=True)
        args: Namespace = Namespace(num_rounds=1)
        run_inputs: Dict[str, Any] = self._run_inputs([1, 1], 5)
        stage_run: StageRun = StageRun(args, stage_executor, run_inputs)
        stages_outcome: Dict[str, Any] = stage_run.run()
        aborted: bool = stages_outcome.get("aborted")
        stage_summaries: List[Dict[str, Any]] = stages_outcome.get("stage_summaries")
        stage_count: int = len(stage_summaries)
        self.assertTrue(aborted)
        self.assertEqual(stage_count, 1)

    def test_probe_result_counts_only_in_the_first_stage(self) -> None:
        """
        Once a stage uses the dry-run probe result, later stages get None.
        """
        stage_executor: MagicMock = self._stage_executor(timeout_reached=False, should_abort=False)
        args: Namespace = Namespace(num_rounds=1)
        run_inputs: Dict[str, Any] = self._run_inputs([1, 1], 5)
        run_inputs["probe_result"] = {"total_tokens": 10}
        stage_run: StageRun = StageRun(args, stage_executor, run_inputs)
        stage_run.run()
        probe_results: List[Any] = self._stage_input_values(stage_executor, "probe_result")
        self.assertEqual(probe_results, [{"total_tokens": 10}, None])

    @staticmethod
    def _stage_executor(timeout_reached: bool, should_abort: bool) -> MagicMock:
        """
        :param timeout_reached: What total_timeout_reached() returns
        :param should_abort: The "should_abort" value of each stage result
        :return: A stand-in StageExecutor whose stages each return a summary
        """
        stage_executor: MagicMock = MagicMock()
        stage_executor.total_timeout_reached.return_value = timeout_reached
        stage_executor.run_single_stage.return_value = {
            "summary": {"concurrent": 1},
            "probe_used": True,
            "should_abort": should_abort,
        }
        return stage_executor

    @staticmethod
    def _run_inputs(stages: List[int], total_cap: int) -> Dict[str, Any]:
        """
        :param stages: Request count of each stage
        :param total_cap: The --max-requests cap
        :return: A run_inputs dict for StageRun
        """
        run_inputs: Dict[str, Any] = {
            "stages": stages,
            "total_cap": total_cap,
            "monitor_resources": False,
            "has_server_log": False,
            "probe_result": None,
            "primary_start_pattern": None,
        }
        return run_inputs

    @staticmethod
    def _stage_input_values(stage_executor: MagicMock, key: str) -> List[Any]:
        """
        :param stage_executor: The stand-in StageExecutor after the run
        :param key: A key of the stage_inputs dict passed to run_single_stage()
        :return: The value of that key for each stage that ran
        """
        values: List[Any] = []
        stage_calls: List[_Call] = stage_executor.run_single_stage.call_args_list
        stage_call: _Call
        # Read the key from the stage_inputs dict of each run_single_stage() call, in run order.
        for stage_call in stage_calls:
            stage_inputs: Dict[str, Any] = stage_call.args[0]
            value: Any = stage_inputs.get(key)
            values.append(value)
        return values
