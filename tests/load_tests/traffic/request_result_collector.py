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

from concurrent.futures import as_completed
from concurrent.futures import CancelledError
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from logging import Logger
from logging import getLogger
from threading import Event
from time import perf_counter
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set

from tests.load_tests.load_test_constants import LoadTestConstants


class RequestResultCollector:
    """
    Collects the results of a stage's request futures for TrafficRunner.run_stage().

    Stops at --stage-timeout or Ctrl-C and records the requests still in flight as KILLED.
    """

    # Grace period after Ctrl-C for in-flight requests to wind down before
    # they are recorded as KILLED.
    INTERRUPT_GRACE_SECONDS: float = 2.0

    def __init__(self, futures: List[Future], results_list: List[Dict[str, Any]], start_seconds: float) -> None:
        """
        Constructor.

        :param futures: Futures of the requests fired in this stage
        :param results_list: Receives one RequestResult per future, KILLED for stragglers
        :param start_seconds: perf_counter() when the stage began
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        # The futures not collected yet; collecting a result removes its future.
        self._pending_futures: Set[Future] = set(futures)
        self._results_list: List[Dict[str, Any]] = results_list
        self._start_seconds: float = start_seconds

    def collect_with_timeout(self, stage_timeout_seconds: Optional[float], cancel_event: Event) -> bool:
        """
        Collect future results, cancelling stragglers on timeout/Ctrl-C.

        Polls in short slices so a set cancel_event (Ctrl-C) is noticed promptly.

        :param stage_timeout_seconds: Seconds after which unfinished requests are killed, or None
        :param cancel_event: Set by the Ctrl-C handler to stop collecting early
        :return: True when Ctrl-C stopped the collection
        """
        interrupted: bool = False
        elapsed_seconds: float = 0.0
        remaining_seconds: float = 0.0
        wait_slice_seconds: float = 0.0
        future: Optional[Future] = None
        while self._pending_futures:
            if cancel_event.is_set():
                interrupted = True
                break
            elapsed_seconds = perf_counter() - self._start_seconds
            if stage_timeout_seconds is not None:
                remaining_seconds = stage_timeout_seconds - elapsed_seconds
                if remaining_seconds <= 0:
                    break
                wait_slice_seconds = min(1.0, remaining_seconds)
            else:
                wait_slice_seconds = 1.0
            try:
                # Collect the requests that finish within this slice.
                for future in as_completed(self._pending_futures, timeout=wait_slice_seconds):
                    finished_result: Dict[str, Any] = future.result()
                    self._results_list.append(finished_result)
                    self._pending_futures.discard(future)
            except FutureTimeoutError:
                pass

        reason: str = "Killed by --stage-timeout"
        if interrupted:
            reason = "Killed by Ctrl-C interrupt"
        # Cancel every request that has not finished.
        for future in self._pending_futures:
            future.cancel()
        if interrupted:
            self._collect_during_grace()
        killed: int = self._collect_killed(reason)
        self._log_killed(killed, interrupted, stage_timeout_seconds)
        return interrupted

    def _collect_during_grace(self) -> None:
        """
        Give in-flight requests a short grace to wind down after Ctrl-C.

        Anything still stuck after the grace, or cancelled before it started, stays pending, without blocking on it.
        """
        grace_deadline_seconds: float = perf_counter() + RequestResultCollector.INTERRUPT_GRACE_SECONDS
        remaining_seconds: float = 0.0
        future: Future
        # Wait for each pending request until the grace runs out.
        for future in list(self._pending_futures):
            remaining_seconds = max(0.0, grace_deadline_seconds - perf_counter())
            try:
                grace_result: Dict[str, Any] = future.result(timeout=remaining_seconds)
                self._results_list.append(grace_result)
                self._pending_futures.discard(future)
            except FutureTimeoutError:
                pass
            except CancelledError:
                # A request cancelled before it started stays pending, so _collect_killed() records it as KILLED.
                pass

    def _collect_killed(self, reason: str) -> int:
        """
        Record the futures still pending, KILLED unless they finished meanwhile.

        :param reason: Why the stragglers were killed, saved as their stderr
        :return: Number of pending futures
        """
        killed: int = 0
        future: Future
        # Record each pending request, KILLED unless it finished meanwhile.
        for future in self._pending_futures:
            killed += 1
            if future.cancelled() or not future.done():
                killed_elapsed_seconds: float = perf_counter() - self._start_seconds
                killed_result: Dict[str, Any] = {
                    "request_id": "unknown",
                    "status": LoadTestConstants.STATUS_KILLED,
                    "stdout": "",
                    "stderr": reason,
                    "returncode": -1,
                    "elapsed": killed_elapsed_seconds,
                    "time_to_first_response": 0.0,
                    "prompt": "",
                }
                self._results_list.append(killed_result)
            else:
                done_result: Dict[str, Any] = future.result()
                self._results_list.append(done_result)
        return killed

    def _log_killed(self, killed_count: int, interrupted: bool, stage_timeout_seconds: Optional[float]) -> None:
        """
        Log the requests that the stage timeout or Ctrl-C dropped.

        :param killed_count: Number of requests still pending at the end
        :param interrupted: True when Ctrl-C stopped the collection
        :param stage_timeout_seconds: The --stage-timeout value
        """
        if killed_count and not interrupted:
            self.logger.warning("  Stage timeout (%ss) reached — %s request(s) killed.",
                                stage_timeout_seconds, killed_count)
        elif interrupted:
            self.logger.warning(
                "  Interrupted (Ctrl-C) — %s request(s) still "
                "in flight were dropped; reporting completed ones.",
                killed_count,
            )
