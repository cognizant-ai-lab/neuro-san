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
from unittest import TestCase

from tests.load_tests.reporting.resource_reporter import ResourceReporter


class TestResourceReporter(TestCase):
    """
    Unit tests for ResourceReporter: the named table cells of each row and the snapshots kept for the results JSON.
    """

    @staticmethod
    def _snapshot(rss_megabytes: float, threads: int) -> Dict[str, Any]:
        """
        Build a process snapshot with the keys ResourceMonitor.snapshot() returns.

        :param rss_megabytes: Resident memory in MB
        :param threads: Thread count
        :return: The snapshot dict
        """
        snapshot: Dict[str, Any] = {
            "rss_megabytes": rss_megabytes,
            "fds": 12,
            "threads": threads,
            "connections": 3,
            "children": 0,
            "cpu_percent": 5.0,
            "cpu_seconds": 1.5,
        }
        return snapshot

    def test_server_row(self) -> None:
        """
        A server row names its cells in MB and keeps its before/after snapshots.
        """
        reporter: ResourceReporter = ResourceReporter()
        before_snapshot: Dict[str, Any] = TestResourceReporter._snapshot(100.0, 10)
        after_snapshot: Dict[str, Any] = TestResourceReporter._snapshot(120.5, 12)

        row: Dict[str, Any] = reporter.add_resource_row("4", before_snapshot, after_snapshot)

        display: Dict[str, str] = row.get("display")
        before_rss_text: str = display.get("before_rss")
        after_rss_text: str = display.get("after_rss")
        rss_delta_text: str = display.get("rss_delta")
        threads_text: str = display.get("threads")
        thread_delta_text: str = display.get("thread_delta")
        self.assertEqual("100.0 MB", before_rss_text)
        self.assertEqual("120.5 MB", after_rss_text)
        self.assertEqual("+20.5 MB", rss_delta_text)
        self.assertEqual("10 -> 12", threads_text)
        self.assertEqual("+2", thread_delta_text)
        snapshots: List[Dict[str, Any]] = reporter.get_resource_snapshots()
        expected_snapshot: Dict[str, Any] = {
            "before": before_snapshot,
            "after": after_snapshot,
        }
        self.assertEqual([expected_snapshot], snapshots)

    def test_client_row_without_peak(self) -> None:
        """
        A client row with no peak snapshot shows "-" for peak RSS and keeps {} as its peak.
        """
        reporter: ResourceReporter = ResourceReporter()
        before_snapshot: Dict[str, Any] = TestResourceReporter._snapshot(50.0, 4)
        settled_snapshot: Dict[str, Any] = TestResourceReporter._snapshot(58.2, 4)

        row: Dict[str, Any] = reporter.add_client_row("4", before_snapshot, None, settled_snapshot)

        display: Dict[str, str] = row.get("display")
        peak_rss_text: str = display.get("peak_rss")
        settled_rss_text: str = display.get("settled_rss")
        rss_delta_text: str = display.get("rss_delta")
        self.assertEqual("-", peak_rss_text)
        self.assertEqual("58.2 MB", settled_rss_text)
        self.assertEqual("+8.2 MB", rss_delta_text)
        snapshots: List[Dict[str, Any]] = reporter.get_client_snapshots()
        expected_snapshot: Dict[str, Any] = {
            "before": before_snapshot,
            "peak": {},
            "settled": settled_snapshot,
        }
        self.assertEqual([expected_snapshot], snapshots)
