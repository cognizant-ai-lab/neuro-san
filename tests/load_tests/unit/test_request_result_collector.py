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
        futures: List[Future] = [TestRequestResultCollector._done_future(1), TestRequestResultCollector._done_future(2)]
        results: List[Dict[str, Any]] = []
        collector: RequestResultCollector = RequestResultCollector(futures, results, perf_counter())
        interrupted: bool = collector.collect_with_timeout(None, Event())
        request_ids: List[Any] = []
        result: Dict[str, Any]
        # Keep the request id of each collected result.
        for result in results:
            request_ids.append(result.get("request_id"))
        sorted_request_ids: List[Any] = sorted(request_ids)
        self.assertFalse(interrupted)
        self.assertEqual([1, 2], sorted_request_ids)

    def test_stage_timeout_kills_unfinished_requests(self) -> None:
        """
        A future still running at the stage timeout is recorded as KILLED by --stage-timeout.
        """
        results: List[Dict[str, Any]] = []
        collector: RequestResultCollector = RequestResultCollector([Future()], results, perf_counter())
        with self.assertLogs("RequestResultCollector", level="WARNING"):
            interrupted: bool = collector.collect_with_timeout(0.1, Event())
        self.assertFalse(interrupted)
        self.assertEqual(1, len(results))
        killed_result: Dict[str, Any] = results[0]
        self.assertEqual(LoadTestConstants.STATUS_KILLED, killed_result.get("status"))
        self.assertEqual("Killed by --stage-timeout", killed_result.get("stderr"))

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
        collector: RequestResultCollector = RequestResultCollector([running_future], results, perf_counter())
        with patch.object(RequestResultCollector, "INTERRUPT_GRACE_SECONDS", 0.1), \
                self.assertLogs("RequestResultCollector", level="WARNING"):
            interrupted: bool = collector.collect_with_timeout(None, cancel_event)
        self.assertTrue(interrupted)
        self.assertEqual(1, len(results))
        killed_result: Dict[str, Any] = results[0]
        self.assertEqual(LoadTestConstants.STATUS_KILLED, killed_result.get("status"))
        self.assertEqual("Killed by Ctrl-C interrupt", killed_result.get("stderr"))

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
