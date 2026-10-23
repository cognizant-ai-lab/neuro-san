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

from psutil import Process

from tests.load_tests.monitoring.resource_monitor import ResourceMonitor


class TestResourceMonitor(TestCase):
    """
    Unit tests for ResourceMonitor: CPU cores in use and the keys of a process snapshot.
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
