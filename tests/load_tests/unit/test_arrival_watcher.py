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

from os.path import exists
from os.path import join
from tempfile import TemporaryDirectory
from threading import Event
from threading import Thread
from time import perf_counter
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase

from tests.load_tests.monitoring.arrival_watcher import ArrivalWatcher


class TestArrivalWatcher(TestCase):
    """
    The ArrivalWatcher thread, fed a server log with two primary request arrivals and one other line.
    """

    LOG_LINES: List[str] = [
        "[1] Start hello_world/streaming_chat",
        "Request handler stream closed.",
        "[2] Start hello_world/streaming_chat",
    ]

    def test_arrivals_go_to_the_receipt_file_when_there_is_an_output_dir(self) -> None:
        """
        With an output directory, each arrival is one line of server_receipts.log, numbered in order.
        """
        with TemporaryDirectory() as output_dir:
            server_log: str = TestArrivalWatcher._write_log(output_dir)
            settings: Dict[str, Any] = TestArrivalWatcher._settings()
            watcher: ArrivalWatcher = ArrivalWatcher(settings)
            monitor: Thread = watcher.start(server_log, 0, output_dir)
            monitor.join(timeout=10)
            monitor_alive: bool = monitor.is_alive()
            self.assertFalse(monitor_alive)
            receipt_path: str = join(output_dir, ArrivalWatcher.RECEIPT_FILE_NAME)
            with open(receipt_path, "r", encoding="utf-8") as receipt_file:
                receipt_lines: List[str] = receipt_file.readlines()
        receipt_count: int = len(receipt_lines)
        self.assertEqual(receipt_count, 2)
        self.assertIn("[server] hello_world request 1/2 received", receipt_lines[0])
        self.assertIn("[server] hello_world request 2/2 received", receipt_lines[1])

    def test_arrivals_are_logged_when_there_is_no_output_dir(self) -> None:
        """
        Without an output directory, each arrival is logged to the console and no receipt file is written.
        """
        with TemporaryDirectory() as log_dir:
            server_log: str = TestArrivalWatcher._write_log(log_dir)
            settings: Dict[str, Any] = TestArrivalWatcher._settings()
            watcher: ArrivalWatcher = ArrivalWatcher(settings)
            with self.assertLogs("ArrivalWatcher", level="INFO") as captured:
                monitor: Thread = watcher.start(server_log, 0)
                monitor.join(timeout=10)
            receipt_path: str = join(log_dir, ArrivalWatcher.RECEIPT_FILE_NAME)
            receipt_exists: bool = exists(receipt_path)
            self.assertFalse(receipt_exists)
        arrival_lines: List[str] = []
        output_line: str
        # Keep only the arrival lines of the captured log output.
        for output_line in captured.output:
            if "received [" in output_line:
                arrival_lines.append(output_line)
        arrival_count: int = len(arrival_lines)
        self.assertEqual(arrival_count, 2, captured.output)
        self.assertIn("hello_world request 2/2 received", arrival_lines[1])

    @staticmethod
    def _settings() -> Dict[str, Any]:
        """
        Build the watcher settings for two arrivals of hello_world.

        :return: The arrival settings, with no client process
        """
        fire_time_seconds: float = perf_counter()
        settings: Dict[str, Any] = {
            "expected_count": 2,
            "fire_time_seconds": fire_time_seconds,
            "stop_event": Event(),
            "client_process": None,
            "primary_start_pattern": r"Start hello_world/streaming_chat",
        }
        return settings

    @staticmethod
    def _write_log(log_dir: str) -> str:
        """
        Write the scratch server log.

        :param log_dir: Directory for the log
        :return: Path of the server log
        """
        server_log: str = join(log_dir, "server.log")
        with open(server_log, "w", encoding="utf-8") as log_file:
            joined_lines: str = "\n".join(TestArrivalWatcher.LOG_LINES)
            log_text: str = joined_lines + "\n"
            log_file.write(log_text)
        return server_log
