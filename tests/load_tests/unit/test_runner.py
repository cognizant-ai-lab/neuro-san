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

from functools import partial
from time import sleep
from time import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.traffic.agent_request_executor import AgentRequestExecutor
from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.traffic.runner import TrafficRunner
from tests.load_tests.traffic.stage_plan import StagePlan
from tests.load_tests.unit.traffic_runner_test_helpers import TrafficRunnerTestHelpers


class TestTrafficRunner(TestCase):
    """
    Unit tests for TrafficRunner: the failure reason run_one_http() gives each request status,
    and how run_stage() collects results and kills requests past --stage-timeout.
    """

    def test_created_request_keeps_timing_and_timestamps(self) -> None:
        """
        A CREATED request with passing checks has no failure, a duration and wall-clock start/end times.
        """
        start_wall_clock_seconds: float = time()
        answer_processor: BasicMessageProcessor = TestTrafficRunner._processor("hi")
        response: Dict[str, Any] = {
            "processor": answer_processor,
            "response_text": "hi",
            "time_to_first_response_seconds": 0.1,
        }
        request_result: AgentRequestResult = AgentRequestResult(LoadTestConstants.STATUS_CREATED, response)
        result: Dict[str, Any] = self._run_one_http(request_result)
        status: str = result.get("status")
        failure_reason: Optional[str] = result.get("failure_reason")
        error: Optional[str] = result.get("error")
        elapsed_seconds: float = result.get("elapsed")
        start_time: float = result.get("start_time")
        end_time: float = result.get("end_time")
        expected_end_time: float = start_time + elapsed_seconds
        self.assertEqual(LoadTestConstants.STATUS_CREATED, status)
        self.assertIsNone(failure_reason)
        self.assertIsNone(error)
        self.assertGreaterEqual(elapsed_seconds, 0.0)
        self.assertGreaterEqual(start_time, start_wall_clock_seconds)
        self.assertAlmostEqual(expected_end_time, end_time)

    def test_failed_request_with_traceback_reports_its_last_line(self) -> None:
        """
        A FAILED request whose response text is a traceback reports the traceback's last line.
        """
        traceback: str = "Traceback (most recent call last):\n  File \"x.py\"\nValueError: boom"
        request_result: AgentRequestResult = AgentRequestResult(LoadTestConstants.STATUS_FAILED,
                                                                {"response_text": traceback})
        result: Dict[str, Any] = self._run_one_http(request_result)
        status: str = result.get("status")
        failure_reason: Optional[str] = result.get("failure_reason")
        error: Optional[str] = result.get("error")
        self.assertEqual(LoadTestConstants.STATUS_FAILED, status)
        self.assertEqual("ValueError: boom", failure_reason)
        self.assertEqual("ValueError: boom", error)

    def test_failed_request_without_response_text(self) -> None:
        """
        A FAILED request with no response text reports an empty response.
        """
        request_result: AgentRequestResult = AgentRequestResult(LoadTestConstants.STATUS_FAILED, {})
        result: Dict[str, Any] = self._run_one_http(request_result)
        failure_reason: Optional[str] = result.get("failure_reason")
        self.assertEqual("empty response from agent", failure_reason)

    def test_timed_out_request_has_no_failure_reason(self) -> None:
        """
        A TIMEOUT request keeps its status and has no failure reason.
        """
        request_result: AgentRequestResult = AgentRequestResult(LoadTestConstants.STATUS_TIMEOUT, {})
        result: Dict[str, Any] = self._run_one_http(request_result)
        status: str = result.get("status")
        failure_reason: Optional[str] = result.get("failure_reason")
        self.assertEqual(LoadTestConstants.STATUS_TIMEOUT, status)
        self.assertIsNone(failure_reason)

    def test_timed_out_request_keeps_its_read_timeout_reason(self) -> None:
        """
        A TIMEOUT request that ran out of the read timeout reports the reason AgentRequestExecutor gave.
        """
        reason: str = "requests.exceptions.ConnectionError: HTTPConnectionPool(host='h', port=1): Read timed out."
        request_result: AgentRequestResult = AgentRequestResult(LoadTestConstants.STATUS_TIMEOUT,
                                                                {"failure_reason": reason})
        result: Dict[str, Any] = self._run_one_http(request_result)
        status: str = result.get("status")
        failure_reason: Optional[str] = result.get("failure_reason")
        self.assertEqual(LoadTestConstants.STATUS_TIMEOUT, status)
        self.assertEqual(reason, failure_reason)

    def test_run_stage_collects_every_request(self) -> None:
        """
        run_stage() returns one result per request, numbered from the plan's global offset.
        """
        stage: Optional[Dict[str, Any]] = None
        fake_request: partial = partial(TestTrafficRunner._fake_request, 0.0)
        with patch.object(TrafficRunner, "run_one_http", side_effect=fake_request):
            stage = TrafficRunnerTestHelpers.create_runner().run_stage(StagePlan(3, 2, 10, None))
        global_ids: List[int] = []
        result: Dict[str, Any]
        # Collect the global request id of each result
        for result in stage.get("results"):
            global_ids.append(result.get("global_request_id"))
        self.assertEqual([10, 11, 12], sorted(global_ids))
        self.assertGreaterEqual(stage.get("total_time_seconds"), 0.0)
        self.assertFalse(stage.get("server_died"))
        self.assertFalse(stage.get("interrupted"))

    def test_run_stage_kills_requests_past_stage_timeout(self) -> None:
        """
        Requests still running at --stage-timeout come back KILLED with the reason as stderr.
        """
        stage: Optional[Dict[str, Any]] = None
        fake_request: partial = partial(TestTrafficRunner._fake_request, 0.5)
        with patch.object(TrafficRunner, "run_one_http", side_effect=fake_request):
            runner: TrafficRunner = TrafficRunnerTestHelpers.create_runner(stage_timeout_seconds=0.1)
            stage = runner.run_stage(StagePlan(2, 2, 0, None))
        self.assertEqual(2, len(stage.get("results")))
        result: Dict[str, Any]
        # Every request comes back killed by the stage timeout
        for result in stage.get("results"):
            self.assertEqual(LoadTestConstants.STATUS_KILLED, result.get("status"))
            self.assertEqual("Killed by --stage-timeout", result.get("stderr"))
        self.assertFalse(stage.get("server_died"))
        self.assertFalse(stage.get("interrupted"))

    def test_run_stage_returns_heartbeat_peaks(self) -> None:
        """
        run_stage() returns the heartbeat's system peaks read after join(), and None for unmonitored processes.
        """
        stage: Optional[Dict[str, Any]] = None
        fake_request: partial = partial(TestTrafficRunner._fake_request, 0.0)
        with patch.object(TrafficRunner, "run_one_http", side_effect=fake_request):
            stage = TrafficRunnerTestHelpers.create_runner().run_stage(StagePlan(1, 1, 0, None))
        self.assertIsNone(stage.get("peak_server_threads"))
        self.assertIsNone(stage.get("peak_client_rss_megabytes"))
        self.assertIsNone(stage.get("peak_server_rss_megabytes"))
        peak_system_memory: Dict[str, float] = stage.get("peak_system_memory")
        self.assertEqual(["available_gigabytes", "memory_percent"], sorted(peak_system_memory.keys()))
        self.assertGreater(peak_system_memory.get("memory_percent"), 0.0)
        self.assertGreaterEqual(stage.get("peak_system_cpu_percent"), 0.0)
        self.assertGreater(stage.get("peak_system_threads"), 0)

    def test_run_stage_counts_failed_requests_on_the_heartbeat(self) -> None:
        """
        Every request that does not end CREATED is counted once on the heartbeat.
        """
        statuses: List[Dict[str, Any]] = [
            {"status": LoadTestConstants.STATUS_CREATED},
            {"status": LoadTestConstants.STATUS_FAILED},
            {"status": LoadTestConstants.STATUS_FAILED},
        ]
        with patch.object(TrafficRunner, "run_one_http", side_effect=statuses), \
                patch.object(Heartbeat, "count_failed_request") as count_failed_request:
            TrafficRunnerTestHelpers.create_runner().run_stage(StagePlan(3, 1, 0, None))
        self.assertEqual(2, count_failed_request.call_count)

    def test_minimal_sends_the_minimal_chat_filter(self) -> None:
        """
        With --minimal, the state the request starts from asks the server for the MINIMAL chat filter.
        """
        answer_processor: BasicMessageProcessor = TestTrafficRunner._processor("hi")
        input_processor: MagicMock = MagicMock()
        input_processor.process_once.return_value = {"last_chat_response": "hi"}
        input_processor.get_message_processor.return_value = answer_processor
        runner: TrafficRunner = TrafficRunnerTestHelpers.create_runner(chat_filter="minimal")
        with patch("tests.load_tests.traffic.agent_request_executor.HttpServiceAgentSession"), \
                patch("tests.load_tests.traffic.agent_request_executor.StreamingInputProcessor",
                      return_value=input_processor):
            runner.run_one_http(1, 0)
        # call_args.args holds the positional arguments of the one process_once() call: the state.
        state: Dict[str, Any] = input_processor.process_once.call_args.args[0]
        state_extractor: DictionaryExtractor = DictionaryExtractor(state)
        chat_filter_type: str = state_extractor.get("chat_filter.chat_filter_type")
        self.assertEqual("MINIMAL", chat_filter_type)

    @staticmethod
    def _processor(answer: str, sly_data: Optional[Dict[str, Any]] = None) -> BasicMessageProcessor:
        """
        Return a BasicMessageProcessor that has seen an AI answer, then the
        final AGENT_FRAMEWORK message that carries chat_context and sly_data
        (the shape a streaming_chat stream ends with).

        :param answer: Text of the AI message
        :param sly_data: sly_data of the final AGENT_FRAMEWORK message, or None to send no such message
        :return: The processor
        """
        processor: BasicMessageProcessor = BasicMessageProcessor()
        processor.process_message({
            "type": "AI",
            "text": answer,
        })
        if sly_data is not None:
            processor.process_message({
                "type": "AGENT_FRAMEWORK",
                "chat_context": {},
                "sly_data": sly_data,
            })
        return processor

    def _run_one_http(self, request_result: AgentRequestResult) -> Dict[str, Any]:
        """
        Run one request whose AgentRequestExecutor returns request_result.

        :param request_result: What the patched AgentRequestExecutor.execute_request() returns
        :return: The request result from run_one_http()
        """
        with patch.object(AgentRequestExecutor, "execute_request", return_value=request_result):
            return TrafficRunnerTestHelpers.create_runner().run_one_http(1, 0)

    @staticmethod
    def _fake_request(delay_seconds: float, request_id: int, global_request_id: int,
                      output_dir: Optional[str]) -> Dict[str, Any]:
        """
        Stand in for run_one_http(), echoing its request numbers after a delay.

        :param delay_seconds: Seconds to sleep before returning
        :param request_id: Request number within the current stage
        :param global_request_id: Request number across the whole run
        :param output_dir: Directory for per-request output files, or None
        :return: A CREATED request result
        """
        sleep(delay_seconds)
        fake_result: Dict[str, Any] = {
            "request_id": f"request-{request_id}",
            "status": LoadTestConstants.STATUS_CREATED,
            "global_request_id": global_request_id,
            "output_dir": output_dir,
        }
        return fake_result
