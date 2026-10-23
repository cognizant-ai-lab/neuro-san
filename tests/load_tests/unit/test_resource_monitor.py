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

from logging import LogRecord
from types import SimpleNamespace
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase
from unittest.mock import patch

from psutil import Process

from tests.load_tests.monitoring.resource_monitor import ResourceMonitor


class TestResourceMonitor(TestCase):
    """
    Unit tests for ResourceMonitor: CPU cores in use, the keys of a process snapshot and the system memory text.
    """

    def test_cores_in_use(self) -> None:
        """
        A whole-system CPU percentage becomes the number of cores it keeps busy.
        """
        half_of_four: float = ResourceMonitor.cores_in_use(50.0, 4)
        none_of_eight: float = ResourceMonitor.cores_in_use(0.0, 8)

        self.assertEqual(2.0, half_of_four)
        self.assertEqual(0.0, none_of_eight)

    def test_snapshot_keys_carry_units(self) -> None:
        """
        A snapshot of this test process names its memory and CPU keys with their units.
        """
        process_snapshot: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(Process())

        self.assertIsNotNone(process_snapshot)
        snapshot_keys: List[str] = sorted(process_snapshot.keys())
        expected_keys: List[str] = sorted(
            ["rss_megabytes", "fds", "threads", "connections", "children", "cpu_percent", "cpu_seconds"]
        )
        self.assertEqual(expected_keys, snapshot_keys)

    def test_snapshot_of_no_process(self) -> None:
        """
        No process gives no snapshot.
        """
        self.assertIsNone(ResourceMonitor.snapshot(None))

    def test_system_memory_text(self) -> None:
        """
        The heartbeat system memory part shows used memory in MB and free memory in GB.
        """
        memory_stats: SimpleNamespace = TestResourceMonitor._fake_memory_stats()

        memory_text: str = ResourceMonitor.system_memory_text(memory_stats)

        self.assertEqual("  sysmem: 75% (6144 MB used / 2.0 GB free)", memory_text)

    def test_log_system_memory(self) -> None:
        """
        The system memory log line names its label and shows MB used, GB free and GB total.
        """
        memory_stats: SimpleNamespace = TestResourceMonitor._fake_memory_stats()

        with patch("tests.load_tests.monitoring.resource_monitor.virtual_memory", return_value=memory_stats):
            with self.assertLogs("tests.load_tests.monitoring.resource_monitor", level="INFO") as captured:
                ResourceMonitor.log_system_memory("BEFORE")

        messages: List[str] = TestResourceMonitor._messages(captured.records)
        expected_line: str = "  System BEFORE: 75% used (6144 MB used / 2.0 GB free / 8.0 GB total)"
        self.assertEqual([expected_line], messages)

    @staticmethod
    def _fake_memory_stats() -> SimpleNamespace:
        """
        Build a stand-in for psutil.virtual_memory(): 8 GB total, 2 GB available, 75% used.

        :return: Object with the total, available and percent attributes
        """
        total_bytes: int = 8 * ResourceMonitor.ONE_GIGABYTE
        available_bytes: int = 2 * ResourceMonitor.ONE_GIGABYTE
        memory_stats: SimpleNamespace = SimpleNamespace(total=total_bytes, available=available_bytes, percent=75.0)
        return memory_stats

    @staticmethod
    def _messages(records: List[LogRecord]) -> List[str]:
        """
        Return the formatted message of each captured log record.

        :param records: The log records captured by assertLogs()
        :return: One message per record
        """
        messages: List[str] = []
        record: LogRecord
        # Keep only the message text, without the level and logger name.
        for record in records:
            messages.append(record.getMessage())
        return messages
