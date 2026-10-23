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

import os
import threading
import time
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from tests.load_tests.load_test_constants import PROGRESS_LOG_FILE_NAME
from tests.load_tests.load_test_constants import STATUS_CREATED
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.traffic.runner import TrafficRunner
from tests.load_tests.unit.traffic_runner_test_helpers import TrafficRunnerTestHelpers


class TestHeartbeat(TestCase):
    """
    Unit tests for Heartbeat: its progress.log lines, its failed-request count and its peak readings.

    Heartbeat writes its progress lines to progress.log without removing the request lines TrafficRunner writes there.
    """

    def test_progress_log_keeps_request_lines_written_before_the_heartbeat(self) -> None:
        """
        A request line TrafficRunner writes before the heartbeat opens progress.log is still there, next to the tick.
        """
        runner: TrafficRunner = TrafficRunnerTestHelpers.create_runner()
        processor: BasicMessageProcessor = BasicMessageProcessor()
        request_result: AgentRequestResult = AgentRequestResult(STATUS_CREATED, processor, "hi", 0.1, {})
        with TemporaryDirectory() as output_dir:
            with patch("tests.load_tests.traffic.agent_request_executor.AgentRequestExecutor.execute_request",
                       return_value=request_result):
                runner.run_one_http(1, 0, output_dir)
            heartbeat: Heartbeat = Heartbeat(None, output_dir=output_dir)
            start_seconds: float = time.perf_counter()
            # With every event already set, progress_heartbeat() writes one tick and returns.
            stop_event: threading.Event = TestHeartbeat._set_event()
            ready_event: threading.Event = TestHeartbeat._set_event()
            fires_done_event: threading.Event = TestHeartbeat._set_event()
            server_dead_event: threading.Event = TestHeartbeat._set_event()
            heartbeat.progress_heartbeat([], 1, start_seconds, stop_event, ready_event, fires_done_event,
                                         server_dead_event)
            with open(os.path.join(output_dir, PROGRESS_LOG_FILE_NAME), encoding="utf-8") as progress_log:
                progress_text: str = progress_log.read()
        self.assertIn("Request 1: CREATED", progress_text)
        self.assertIn("[progress] 0 of 1 completed", progress_text)

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
        A peak is only kept for a reading above zero and above the peak so far.
        """
        self.assertFalse(Heartbeat.is_new_peak(0, None))
        self.assertTrue(Heartbeat.is_new_peak(5, None))
        self.assertFalse(Heartbeat.is_new_peak(5, 5))
        self.assertTrue(Heartbeat.is_new_peak(6.5, 5))

    @staticmethod
    def _set_event() -> threading.Event:
        """
        Make an event that is already set.

        :return: The set event
        """
        event: threading.Event = threading.Event()
        event.set()
        return event
