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

from time import perf_counter
from typing import Optional
from unittest import TestCase

from tests.load_tests.monitoring.stall_tracker import StallTracker


class TestStallTracker(TestCase):
    """
    Unit tests for StallTracker: a done count that did not change since the last call is stalled.
    """

    def test_unchanged_done_count_is_stalled(self) -> None:
        """
        The same done count twice, with requests left, gives the seconds since the stage start.
        """
        tracker: StallTracker = StallTracker()
        start_seconds: float = perf_counter() - 30.0
        tracker.start(start_seconds)
        stalled_seconds: Optional[int] = tracker.stalled_seconds(0, 3)
        self.assertEqual(30, stalled_seconds)

    def test_changed_done_count_is_not_stalled(self) -> None:
        """
        A done count that went up is not stalled, and the next unchanged call counts from that change.
        """
        tracker: StallTracker = StallTracker()
        start_seconds: float = perf_counter() - 30.0
        tracker.start(start_seconds)
        first_seconds: Optional[int] = tracker.stalled_seconds(1, 3)
        second_seconds: Optional[int] = tracker.stalled_seconds(1, 3)
        self.assertIsNone(first_seconds)
        self.assertEqual(0, second_seconds)

    def test_all_done_is_not_stalled(self) -> None:
        """
        Once every request is done nothing is stalled.
        """
        tracker: StallTracker = StallTracker()
        start_seconds: float = perf_counter() - 30.0
        tracker.start(start_seconds)
        tracker.stalled_seconds(3, 3)
        stalled_seconds: Optional[int] = tracker.stalled_seconds(3, 3)
        self.assertIsNone(stalled_seconds)
