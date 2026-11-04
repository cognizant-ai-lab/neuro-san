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

from os.path import join
from tempfile import TemporaryDirectory
from threading import Event
from time import perf_counter
from typing import Any
from typing import Dict
from unittest import TestCase
from unittest.mock import patch

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.traffic.traffic_runner import TrafficRunner
from tests.load_tests.unit.traffic_runner_test_helpers import TrafficRunnerTestHelpers


class TestHeartbeat(TestCase):
    """
    Unit tests for Heartbeat: its progress.log lines and its failed-request count.

    Heartbeat writes its progress lines to progress.log without removing the request lines TrafficRunner writes there.
    """

    def test_progress_log_keeps_request_lines_written_before_the_heartbeat(self) -> None:
        """
        A request line TrafficRunner writes before the heartbeat opens progress.log is still there, next to the tick.
        """
        runner: TrafficRunner = TrafficRunnerTestHelpers.create_runner()
        processor: BasicMessageProcessor = BasicMessageProcessor()
        response: Dict[str, Any] = {
            "processor": processor,
            "response_text": "hi",
            "time_to_first_response_seconds": 0.1,
        }
        request_result: AgentRequestResult = AgentRequestResult(LoadTestConstants.STATUS_CREATED, response)
        progress_text: str = ""
        with TemporaryDirectory() as output_dir:
            with patch("tests.load_tests.traffic.agent_request_executor.AgentRequestExecutor.execute_request",
                       return_value=request_result):
                runner.run_one_http(1, 0, output_dir)
            heartbeat: Heartbeat = Heartbeat(None, output_dir=output_dir)
            start_seconds: float = perf_counter()
            heartbeat_events: Dict[str, Event] = {}
            event_name: str
            # With every event already set, progress_heartbeat() writes one tick and returns.
            for event_name in ["stop_event", "ready_event", "fires_done_event", "server_dead_event"]:
                heartbeat_events[event_name] = TestHeartbeat._set_event()
            heartbeat.progress_heartbeat([], 1, start_seconds, heartbeat_events)
            progress_log_path: str = join(output_dir, LoadTestConstants.PROGRESS_LOG_FILE_NAME)
            with open(progress_log_path, encoding="utf-8") as progress_log:
                progress_text = progress_log.read()
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

    def test_duration_stats_print_minutes_and_seconds(self) -> None:
        """
        Request durations of a minute or more print as minutes and seconds, shorter ones as seconds.
        """
        stats_text: str = Heartbeat.format_duration_stats([45.7, 90.2, 125.9])
        no_stats_text: str = Heartbeat.format_duration_stats([])
        self.assertEqual("45s min / 1m 27s avg / 2m 5s max", stats_text)
        self.assertEqual("n/a", no_stats_text)

    @staticmethod
    def _set_event() -> Event:
        """
        Make an event that is already set.

        :return: The set event
        """
        event: Event = Event()
        event.set()
        return event
