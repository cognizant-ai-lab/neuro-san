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
from concurrent.futures import Future
from threading import Event
from time import perf_counter
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.traffic.request_result_collector import RequestResultCollector


class TestRequestResultCollector(TestCase):
    """
    Unit tests for RequestResultCollector: collected results, the stage timeout and Ctrl-C.
    """

    def test_collects_every_finished_request(self) -> None:
        """
        Every finished future gives its result, and the collection is not interrupted.
        """
        first_future: Future = TestRequestResultCollector._done_future(1)
        second_future: Future = TestRequestResultCollector._done_future(2)
        futures: List[Future] = [first_future, second_future]
        results: List[Dict[str, Any]] = []
        start_seconds: float = perf_counter()
        collector: RequestResultCollector = RequestResultCollector(futures, results, start_seconds)
        cancel_event: Event = Event()
        interrupted: bool = collector.collect_with_timeout(None, cancel_event)
        request_ids: List[Any] = []
        result: Dict[str, Any]
        # Keep the request id of each collected result.
        for result in results:
            request_id: Any = result.get("request_id")
            request_ids.append(request_id)
        sorted_request_ids: List[Any] = sorted(request_ids)
        self.assertFalse(interrupted)
        self.assertEqual([1, 2], sorted_request_ids)

    def test_stage_timeout_kills_unfinished_requests(self) -> None:
        """
        A future still running at the stage timeout is recorded as KILLED by --stage-timeout.
        """
        results: List[Dict[str, Any]] = []
        unfinished_future: Future = Future()
        start_seconds: float = perf_counter()
        collector: RequestResultCollector = RequestResultCollector([unfinished_future], results, start_seconds)
        cancel_event: Event = Event()
        with self.assertLogs("RequestResultCollector", level="WARNING") as captured:
            interrupted: bool = collector.collect_with_timeout(0.1, cancel_event)
        warning_line: str = captured.output[0]
        result_count: int = len(results)
        killed_result: Dict[str, Any] = results[0]
        status: str = killed_result.get("status")
        stderr: str = killed_result.get("stderr")
        self.assertFalse(interrupted)
        self.assertIn("Stage timeout (0.1s) reached", warning_line)
        self.assertEqual(1, result_count)
        self.assertEqual(LoadTestConstants.STATUS_KILLED, status)
        self.assertEqual("Killed by --stage-timeout", stderr)

    def test_ctrl_c_stops_the_collection(self) -> None:
        """
        A set cancel event stops the collection and records the request still running as KILLED by Ctrl-C.
        """
        cancel_event: Event = Event()
        cancel_event.set()
        # A running future cannot be cancelled, so it is still pending after the grace.
        running_future: Future = Future()
        running_future.set_running_or_notify_cancel()
        results: List[Dict[str, Any]] = []
        start_seconds: float = perf_counter()
        collector: RequestResultCollector = RequestResultCollector([running_future], results, start_seconds)
        with patch.object(RequestResultCollector, "INTERRUPT_GRACE_SECONDS", 0.1), \
                self.assertLogs("RequestResultCollector", level="WARNING") as captured:
            interrupted: bool = collector.collect_with_timeout(None, cancel_event)
        warning_line: str = captured.output[0]
        result_count: int = len(results)
        killed_result: Dict[str, Any] = results[0]
        status: str = killed_result.get("status")
        stderr: str = killed_result.get("stderr")
        self.assertTrue(interrupted)
        self.assertIn("Interrupted (Ctrl-C)", warning_line)
        self.assertEqual(1, result_count)
        self.assertEqual(LoadTestConstants.STATUS_KILLED, status)
        self.assertEqual("Killed by Ctrl-C interrupt", stderr)

    def test_ctrl_c_records_never_started_requests_as_killed(self) -> None:
        """
        A request cancelled by Ctrl-C before it started is recorded as KILLED, not dropped.
        """
        cancel_event: Event = Event()
        cancel_event.set()
        # A pending future that is not running is cancelled by the collection, as a queued request is.
        queued_future: Future = Future()
        results: List[Dict[str, Any]] = []
        start_seconds: float = perf_counter()
        collector: RequestResultCollector = RequestResultCollector([queued_future], results, start_seconds)
        with patch.object(RequestResultCollector, "INTERRUPT_GRACE_SECONDS", 0.1), \
                self.assertLogs("RequestResultCollector", level="WARNING") as captured:
            interrupted: bool = collector.collect_with_timeout(None, cancel_event)
        warning_line: str = captured.output[0]
        result_count: int = len(results)
        killed_result: Dict[str, Any] = results[0]
        status: str = killed_result.get("status")
        is_cancelled: bool = queued_future.cancelled()
        self.assertTrue(interrupted)
        self.assertIn("Interrupted (Ctrl-C)", warning_line)
        self.assertTrue(is_cancelled)
        self.assertEqual(1, result_count)
        self.assertEqual(LoadTestConstants.STATUS_KILLED, status)

    @staticmethod
    def _done_future(request_id: int) -> Future:
        """
        Return a future that already holds a result.

        :param request_id: Request id of the result
        :return: The finished future
        """
        future: Future = Future()
        future.set_result({"request_id": request_id})
        return future
