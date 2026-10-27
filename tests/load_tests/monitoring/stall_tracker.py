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


class StallTracker:
    """
    Notes when the stage's done count last changed, so the heartbeat can report requests that are stalled.

    Only the heartbeat thread calls it, so it needs no lock.
    """

    def __init__(self) -> None:
        """
        Constructor.
        """
        self._last_done_count: int = 0
        self._last_change_seconds: float = 0.0

    def start(self, start_seconds: float) -> None:
        """
        Start tracking a new stage with no request done yet.

        :param start_seconds: perf_counter() value taken when the stage began
        """
        self._last_done_count = 0
        self._last_change_seconds = start_seconds

    def stalled_seconds(self, done_count: int, total: int) -> Optional[int]:
        """
        Tell how long the done count has not changed, and note when it changes.

        :param done_count: Requests finished so far
        :param total: Number of requests in this stage
        :return: Whole seconds since the done count last changed, or None when it changed
            since the last call or every request is done
        """
        stalled_seconds: Optional[int] = None
        if done_count == self._last_done_count and done_count < total:
            stalled_seconds = int(perf_counter() - self._last_change_seconds)
        if done_count > self._last_done_count:
            self._last_change_seconds = perf_counter()
            self._last_done_count = done_count
        return stalled_seconds
