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
"""
Unit tests for TrafficRunner response checks via the data-driven evaluators.
"""

import threading
import time
from argparse import Namespace
from functools import partial
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from unittest import TestCase
from unittest.mock import patch

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.traffic.agent_request_executor import AgentRequestExecutor
from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.traffic.runner import TrafficRunner
from tests.load_tests.traffic.stage_plan import StagePlan


class TestRunnerResponseChecks(TestCase):
    """
    TrafficRunner.check_response hands the hocon response block to
    DataDrivenTestsDriver.test_response_keys and turns the captured
    assertion failures into a failure reason; failure_patterns go
    through the same path as text.not_keywords.

    Also covers the failure reason run_one_http() gives each request status,
    and how run_stage() collects results and kills requests past --stage-timeout.
    """

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
        processor.process_message({"type": "AI", "text": answer})
        if sly_data is not None:
            processor.process_message({"type": "AGENT_FRAMEWORK", "chat_context": {}, "sly_data": sly_data})
        return processor

    @staticmethod
    def _runner(failure_patterns: Optional[List[str]] = None) -> TrafficRunner:
        """
        Return a runner over a one-prompt profile.

        :param failure_patterns: failure_patterns of the profile, or None for none
        :return: The runner
        """
        profile: AgentProfile = AgentProfile("x", {"prompts": ["p"], "failure_patterns": failure_patterns or []})
        return TrafficRunner(Namespace(same_prompt=False), profile, threading.Event())

    def test_no_checks_passes(self) -> None:
        """
        An empty response block and no failure_patterns never fail.
        """
        reason: Optional[str] = self._runner().check_response(self._processor("hi"), {})
        self.assertIsNone(reason)

    def test_not_value_requires_present_non_empty_sly_data(self) -> None:
        """
        sly_data.<key>: { not_value: "" } fails on a missing or empty key.
        """
        checks: Dict[str, Any] = {"sly_data": {"agent_reservations": {"not_value": ""}}}
        runner: TrafficRunner = self._runner()
        reservations: List[Dict[str, Any]] = [{"reservation_id": "r-1"}]
        with_reservations: BasicMessageProcessor = self._processor("ok", {"agent_reservations": reservations})
        without_reservations: BasicMessageProcessor = self._processor("ok", {"agent_network_name": "n"})
        empty_reservations: BasicMessageProcessor = self._processor("ok", {"agent_reservations": ""})
        self.assertIsNone(runner.check_response(with_reservations, checks))
        self.assertIn("agent_reservations", runner.check_response(without_reservations, checks))
        self.assertIn("agent_reservations", runner.check_response(empty_reservations, checks))

    def test_keywords_check_on_answer_text(self) -> None:
        """
        text: { keywords: [...] } is applied to the answer.
        """
        checks: Dict[str, Any] = {"text": {"keywords": ["Bonjour"]}}
        runner: TrafficRunner = self._runner()
        self.assertIsNone(runner.check_response(self._processor("Bonjour!"), checks))
        self.assertIsNotNone(runner.check_response(self._processor("Hello!"), checks))

    def test_failure_patterns_fail_the_request(self) -> None:
        """
        failure_patterns are checked as text.not_keywords.
        """
        runner: TrafficRunner = self._runner(["No fully-specified LLM found"])
        self.assertIsNone(runner.check_response(self._processor("fine"), {}))
        reason: Optional[str] = runner.check_response(self._processor("Error: No fully-specified LLM found"), {})
        self.assertIn("No fully-specified LLM found", reason)

    def test_all_failures_are_reported(self) -> None:
        """
        Every failed check appears in the reason, not just the first.
        """
        checks: Dict[str, Any] = {"sly_data": {"a": {"not_value": ""}, "b": {"not_value": ""}}}
        reason: Optional[str] = self._runner().check_response(self._processor("ok", {}), checks)
        self.assertIn("sly_data.a", reason)
        self.assertIn("sly_data.b", reason)

    @staticmethod
    def _stage_runner(stage_timeout: Optional[float] = None) -> TrafficRunner:
        """
        Return a runner over a one-prompt profile with every argument run_one_http() and run_stage() read.

        :param stage_timeout: Seconds after which run_stage() kills unfinished requests, or None
        :return: The runner
        """
        profile: AgentProfile = AgentProfile("x", {"prompts": ["p"]})
        args: Namespace = Namespace(
            same_prompt=False, allow_caching=False, host="localhost", port=8080, https=False, agent="x",
            chat_filter="maximal",
            request_timeout=5.0, idle_timeout=5.0, include_tokens=False, stage_timeout=stage_timeout,
        )
        return TrafficRunner(args, profile, threading.Event())

    def _run_one_http(self, request_result: AgentRequestResult) -> Dict[str, Any]:
        """
        Run one request whose AgentRequestExecutor returns request_result.

        :param request_result: What the patched AgentRequestExecutor.execute_request() returns
        :return: The request result from run_one_http()
        """
        with patch.object(AgentRequestExecutor, "execute_request", return_value=request_result):
            return self._stage_runner().run_one_http(1, 0)

    @staticmethod
    def _fake_request(delay: float, request_id: int, global_request_id: int,
                      output_dir: Optional[str]) -> Dict[str, Any]:
        """
        Stand in for run_one_http(), echoing its request numbers after a delay.

        :param delay: Seconds to sleep before returning
        :param request_id: Request number within the current stage
        :param global_request_id: Request number across the whole run
        :param output_dir: Directory for per-request output files, or None
        :return: A CREATED request result
        """
        time.sleep(delay)
        fake_result: Dict[str, Any] = {
            "request_id": f"request-{request_id}", "status": STATUS_CREATED,
            "global_request_id": global_request_id, "output_dir": output_dir,
        }
        return fake_result

    def test_created_request_keeps_timing_and_timestamps(self) -> None:
        """
        A CREATED request with passing checks has no failure, a duration and wall-clock start/end times.
        """
        before: float = time.time()
        answer_processor: BasicMessageProcessor = self._processor("hi")
        request_result: AgentRequestResult = AgentRequestResult(STATUS_CREATED, answer_processor, "hi", 0.1, {})
        result: Dict[str, Any] = self._run_one_http(request_result)
        self.assertEqual(STATUS_CREATED, result.get("status"))
        self.assertIsNone(result.get("failure_reason"))
        self.assertIsNone(result.get("error"))
        self.assertGreaterEqual(result.get("elapsed"), 0.0)
        self.assertGreaterEqual(result.get("start_time"), before)
        self.assertAlmostEqual(result.get("start_time") + result.get("elapsed"), result.get("end_time"))

    def test_failed_request_with_traceback_reports_its_last_line(self) -> None:
        """
        A FAILED request whose response text is a traceback reports the traceback's last line.
        """
        traceback: str = "Traceback (most recent call last):\n  File \"x.py\"\nValueError: boom"
        result: Dict[str, Any] = self._run_one_http(AgentRequestResult(STATUS_FAILED, None, traceback, 0.0, {}))
        self.assertEqual(STATUS_FAILED, result.get("status"))
        self.assertEqual("ValueError: boom", result.get("failure_reason"))
        self.assertEqual("ValueError: boom", result.get("error"))

    def test_failed_request_without_response_text(self) -> None:
        """
        A FAILED request with no response text reports an empty response.
        """
        result: Dict[str, Any] = self._run_one_http(AgentRequestResult(STATUS_FAILED, None, "", 0.0, {}))
        self.assertEqual("empty response from agent", result.get("failure_reason"))

    def test_timed_out_request_has_no_failure_reason(self) -> None:
        """
        A TIMEOUT request keeps its status and has no failure reason.
        """
        result: Dict[str, Any] = self._run_one_http(AgentRequestResult(STATUS_TIMEOUT, None, "", 0.0, {}))
        self.assertEqual(STATUS_TIMEOUT, result.get("status"))
        self.assertIsNone(result.get("failure_reason"))

    def test_run_stage_collects_every_request(self) -> None:
        """
        run_stage() returns one result per request, numbered from the plan's global offset.
        """
        stage: Optional[Tuple[float, List[Dict[str, Any]], Optional[int], Optional[float], Optional[float],
                              Optional[Dict[str, float]], Optional[float], Optional[int], bool, bool]] = None
        with patch.object(TrafficRunner, "run_one_http", side_effect=partial(self._fake_request, 0.0)):
            stage = self._stage_runner().run_stage(StagePlan(3, 2, 10, None))
        global_ids: List[int] = []
        for result in stage[1]:
            global_ids.append(result.get("global_request_id"))
        self.assertEqual([10, 11, 12], sorted(global_ids))
        self.assertGreaterEqual(stage[0], 0.0)
        self.assertEqual((False, False), stage[8:])

    def test_run_stage_kills_requests_past_stage_timeout(self) -> None:
        """
        Requests still running at --stage-timeout come back KILLED with the reason as stderr.
        """
        stage: Optional[Tuple[float, List[Dict[str, Any]], Optional[int], Optional[float], Optional[float],
                              Optional[Dict[str, float]], Optional[float], Optional[int], bool, bool]] = None
        with patch.object(TrafficRunner, "run_one_http", side_effect=partial(self._fake_request, 0.5)):
            stage = self._stage_runner(stage_timeout=0.1).run_stage(StagePlan(2, 2, 0, None))
        self.assertEqual(2, len(stage[1]))
        for result in stage[1]:
            self.assertEqual(STATUS_KILLED, result.get("status"))
            self.assertEqual("Killed by --stage-timeout", result.get("stderr"))
        self.assertEqual((False, False), stage[8:])

    def test_run_stage_returns_heartbeat_peaks(self) -> None:
        """
        run_stage() returns the heartbeat's system peaks read after join(), and None for unmonitored processes.
        """
        stage: Optional[Tuple[float, List[Dict[str, Any]], Optional[int], Optional[float], Optional[float],
                              Optional[Dict[str, float]], Optional[float], Optional[int], bool, bool]] = None
        with patch.object(TrafficRunner, "run_one_http", side_effect=partial(self._fake_request, 0.0)):
            stage = self._stage_runner().run_stage(StagePlan(1, 1, 0, None))
        self.assertIsNone(stage[2])
        self.assertIsNone(stage[3])
        self.assertIsNone(stage[4])
        self.assertEqual(["available_gigabytes", "memory_percent"], sorted(stage[5].keys()))
        self.assertGreater(stage[5].get("memory_percent"), 0.0)
        self.assertGreaterEqual(stage[6], 0.0)
        self.assertGreater(stage[7], 0)

    def test_run_stage_counts_failed_requests_on_the_heartbeat(self) -> None:
        """
        Every request that does not end CREATED is counted once on the heartbeat.
        """
        statuses: List[Dict[str, Any]] = [{"status": STATUS_CREATED}, {"status": STATUS_FAILED},
                                          {"status": STATUS_FAILED}]
        with patch.object(TrafficRunner, "run_one_http", side_effect=statuses), \
                patch.object(Heartbeat, "count_failed_request") as count_failed_request:
            self._stage_runner().run_stage(StagePlan(3, 1, 0, None))
        self.assertEqual(2, count_failed_request.call_count)

    def test_heartbeat_failed_request_count(self) -> None:
        """
        The heartbeat's failed count starts at 0 and goes up by one per failed request.
        """
        heartbeat: Heartbeat = Heartbeat(None)
        self.assertEqual(0, heartbeat.get_failed_request_count())
        heartbeat.count_failed_request()
        heartbeat.count_failed_request()
        self.assertEqual(2, heartbeat.get_failed_request_count())

    def test_peaks_ignore_zero_and_lower_readings(self) -> None:
        """
        A peak is only kept for a reading above zero and above the peak so far, the rule used before.
        """
        self.assertFalse(Heartbeat.is_new_peak(0, None))
        self.assertTrue(Heartbeat.is_new_peak(5, None))
        self.assertFalse(Heartbeat.is_new_peak(5, 5))
        self.assertTrue(Heartbeat.is_new_peak(6.5, 5))
