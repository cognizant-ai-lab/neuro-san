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

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase
from unittest.mock import MagicMock

from tests.load_tests.monitoring.server_duration_reader import ServerDurationReader
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor


class TestServerDurationReader(TestCase):
    """
    Unit tests for ServerDurationReader: which Start/Finish pairs of the server log give a duration.
    """

    def test_no_server_log_gives_none(self) -> None:
        """
        Without a log monitor or a start position there is no data source.
        """
        log_monitor: MagicMock = MagicMock(spec=ServerLogMonitor)
        no_settings: ServerDurationReader = ServerDurationReader()
        no_position: ServerDurationReader = ServerDurationReader({"log_monitor": log_monitor})
        no_settings_durations: Optional[List[float]] = no_settings.read_durations()
        no_position_durations: Optional[List[float]] = no_position.read_durations()
        self.assertIsNone(no_settings_durations)
        self.assertIsNone(no_position_durations)

    def test_keeps_primary_agent_durations(self) -> None:
        """
        Only pairs of the primary agent with a duration above zero are kept.
        """
        pairs: List[Dict[str, Any]] = [
            {
                "agent": "hello",
                "duration_seconds": 2.5,
            },
            {
                "agent": "helper",
                "duration_seconds": 4.0,
            },
            {
                "agent": "hello",
                "duration_seconds": 0.0,
            },
        ]
        log_monitor: MagicMock = TestServerDurationReader._log_monitor(pairs)
        reader: ServerDurationReader = TestServerDurationReader._reader(log_monitor)
        durations: Optional[List[float]] = reader.read_durations()
        self.assertEqual([2.5], durations)

    def test_unreadable_log_gives_no_durations(self) -> None:
        """
        A server log that cannot be read gives an empty list, not None.
        """
        log_monitor: MagicMock = TestServerDurationReader._log_monitor([])
        log_monitor.parse_streaming_chat_timing_since.side_effect = OSError("gone")
        reader: ServerDurationReader = TestServerDurationReader._reader(log_monitor)
        durations: Optional[List[float]] = reader.read_durations()
        self.assertEqual([], durations)

    @staticmethod
    def _log_monitor(pairs: List[Dict[str, Any]]) -> MagicMock:
        """
        Make a stand-in ServerLogMonitor that returns the given pairs.

        :param pairs: What its parse_streaming_chat_timing_since() returns
        :return: The stand-in log monitor
        """
        log_monitor: MagicMock = MagicMock(spec=ServerLogMonitor)
        log_monitor.parse_streaming_chat_timing_since.return_value = pairs
        return log_monitor

    @staticmethod
    def _reader(log_monitor: MagicMock) -> ServerDurationReader:
        """
        Make a reader over the given log monitor, from the start of the log.

        :param log_monitor: The stand-in log monitor
        :return: The reader, with the primary agent "hello"
        """
        server_log_timing: Dict[str, Any] = {
            "log_monitor": log_monitor,
            "log_start_position": 0,
            "primary_start_pattern": r"Start hello/streaming_chat",
        }
        return ServerDurationReader(server_log_timing)
