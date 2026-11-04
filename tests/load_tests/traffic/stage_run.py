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

from logging import Logger
from logging import getLogger
from time import perf_counter
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from tests.load_tests.traffic.stage_executor import StageExecutor


class StageRun:
    """
    One run of all the stages of a load test, round by round, and the counts that change as the stages run.
    Stops early at the --max-requests cap, at --total-timeout, or when a stage must abort the test.
    """

    # 60 "#" characters: the line around the round header.
    ROUND_HEADER_LINE: str = "############################################################"

    def __init__(self, num_rounds: int, stage_executor: StageExecutor, run_inputs: Dict[str, Any]) -> None:
        """
        Keep the settings of the run and start its clock.

        :param num_rounds: --num-rounds: rounds of each stage
        :param stage_executor: Runs each stage and checks --total-timeout
        :param run_inputs: A dict with the following keys:
            "stages"                 Request count of each stage, in order
            "total_cap"              Most requests to send in the whole test
            "monitor_resources"      True to take resource snapshots around each stage
            "has_server_log"         True when the server log can be read
            "probe_result"           Result of the dry-run probe to count in the first stage, or None
            "primary_start_pattern"  Server log pattern of a primary request start
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self._stage_executor: StageExecutor = stage_executor
        stages: List[int] = run_inputs.get("stages")
        only_stage: bool = len(stages) == 1 and num_rounds == 1
        test_start_seconds: float = perf_counter()
        self._run_settings: Dict[str, Any] = {
            "stages": stages,
            "total_cap": run_inputs.get("total_cap"),
            "monitor_resources": run_inputs.get("monitor_resources"),
            "has_server_log": run_inputs.get("has_server_log"),
            "primary_start_pattern": run_inputs.get("primary_start_pattern"),
            "only_stage": only_stage,
            "num_rounds": num_rounds,
            "test_start_seconds": test_start_seconds,
        }
        self._total_sent: int = 0
        self._probe_result: Optional[Dict[str, Any]] = run_inputs.get("probe_result")
        self._stage_summaries: List[Dict[str, Any]] = []
        self._aborted: bool = False

    def run(self) -> Dict[str, Any]:
        """
        Run every stage once per round, collecting data per stage.

        :return: A dict with the following keys:
            "stage_summaries"  One summary dict per stage that runs
            "aborted"          True when a stage or --total-timeout stops the test
        """
        num_rounds: int = self._run_settings.get("num_rounds")
        round_num: int
        # Run every stage once per round, until the request cap, the total timeout or a stage stops the test.
        for round_num in range(1, num_rounds + 1):
            if num_rounds > 1:
                self.logger.info("\n%s", StageRun.ROUND_HEADER_LINE)
                self.logger.info("  ROUND %s of %s", round_num, num_rounds)
                self.logger.info("%s", StageRun.ROUND_HEADER_LINE)
            keep_running: bool = self._run_round(round_num)
            if not keep_running:
                break
        stages_outcome: Dict[str, Any] = {
            "stage_summaries": self._stage_summaries,
            "aborted": self._aborted,
        }
        return stages_outcome

    def _run_round(self, round_num: int) -> bool:
        """
        Run the stages of one round, and add up the requests sent and the stage summaries.

        :param round_num: Round number, starting at 1
        :return: True when the next round can run, False when the request cap, the total timeout or a stage
            stops the test
        """
        stages: List[int] = self._run_settings.get("stages")
        total_cap: int = self._run_settings.get("total_cap")
        test_start_seconds: float = self._run_settings.get("test_start_seconds")
        stage_index: int
        num_concurrent: int
        # Run each stage, stopping at the request cap or the total timeout.
        for stage_index, num_concurrent in enumerate(stages):
            if self._request_cap_reached():
                return False
            if self._stage_executor.total_timeout_reached(test_start_seconds):
                self._aborted = True
                return False

            remaining: int = total_cap - self._total_sent
            actual_requests: int = min(num_concurrent, remaining)
            # The requests sent by earlier stages come first, so _total_sent is also this stage's request offset.
            stage_inputs: Dict[str, Any] = {
                "actual_requests": actual_requests,
                "num_concurrent": num_concurrent,
                "stage_num": stage_index + 1,
                "round_num": round_num,
                "global_offset": self._total_sent,
                "monitor_resources": self._run_settings.get("monitor_resources"),
                "has_server_log": self._run_settings.get("has_server_log"),
                "probe_result": self._probe_result,
                "only_stage": self._run_settings.get("only_stage"),
                "primary_start_pattern": self._run_settings.get("primary_start_pattern"),
            }
            stage_result: Dict[str, Any] = self._stage_executor.run_single_stage(stage_inputs)

            self._total_sent += actual_requests
            if stage_result.get("probe_used"):
                self._probe_result = None
            stage_summary: Dict[str, Any] = stage_result.get("summary")
            self._stage_summaries.append(stage_summary)
            if stage_result.get("should_abort"):
                self._aborted = True
                return False
        return True

    def _request_cap_reached(self) -> bool:
        """
        Check the request cap before a stage, and log how to run all planned requests when it is reached.

        :return: True when the --max-requests cap is reached
        """
        stages: List[int] = self._run_settings.get("stages")
        total_cap: int = self._run_settings.get("total_cap")
        num_rounds: int = self._run_settings.get("num_rounds")
        cap_reached: bool = self._total_sent >= total_cap
        if cap_reached:
            total_planned: int = sum(stages) * num_rounds
            self.logger.warning(
                """
WARNING: Reached --max-requests cap (%s). Only %s of %s total planned requests completed.
         Use --max-requests %s to run all planned requests.""",
                total_cap, self._total_sent, total_planned, total_planned,
            )
        return cap_reached
