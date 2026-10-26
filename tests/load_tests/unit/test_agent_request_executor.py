
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
from typing import Any
from typing import Dict
from typing import Optional
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.traffic.agent_request_executor import AgentRequestExecutor
from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.unit.fake_processor import FakeProcessor
from tests.load_tests.unit.fake_session import FakeSession


class TestAgentRequestExecutor(TestCase):
    """
    Unit tests for --request-timeout in the HTTP transport.

    A streaming request that keeps producing messages must still be
    abandoned at the cap: without that, one slow request holds a worker
    for the whole run.
    """

    def test_streaming_past_the_cap_is_a_timeout(self) -> None:
        """
        A stream that outruns the cap reports TIMEOUT.
        """
        run: Dict[str, Any] = self._execute(timeout_seconds=0.3, message_count=20, message_interval_seconds=0.05)
        result: AgentRequestResult = run.get("result")
        status: str = result.get_status()

        self.assertEqual(status, LoadTestConstants.STATUS_TIMEOUT)

    def test_streaming_past_the_cap_stops_early(self) -> None:
        """
        The request is abandoned rather than drained to the end.

        Reporting TIMEOUT after draining the whole stream would still
        label the request correctly, but the worker would stay occupied
        until the stream ends.
        """
        start_seconds: float = perf_counter()
        run: Dict[str, Any] = self._execute(timeout_seconds=0.3, message_count=20, message_interval_seconds=0.05)
        session: FakeSession = run.get("session")
        elapsed_seconds: float = perf_counter() - start_seconds

        self.assertLess(session.sent, 20)
        self.assertLess(elapsed_seconds, 20 * 0.05)

    def test_request_within_the_cap_succeeds(self) -> None:
        """
        A request that finishes in time is unaffected.
        """
        run: Dict[str, Any] = self._execute(timeout_seconds=30, message_count=3, message_interval_seconds=0.01)
        result: AgentRequestResult = run.get("result")
        session: FakeSession = run.get("session")
        status: str = result.get_status()
        response_text: str = result.get_response_text()
        sly_data: Dict[str, Any] = result.get_processor().get_sly_data()
        reservation_id: str = sly_data.get("reservation_id")
        first_response_seconds: float = result.get_time_to_first_response_seconds()

        self.assertEqual(status, LoadTestConstants.STATUS_CREATED)
        self.assertEqual(response_text, "answer")
        self.assertEqual(reservation_id, "abc-1")
        self.assertEqual(session.sent, 3)
        self.assertGreater(first_response_seconds, 0.0)

    def _execute(
            self, timeout_seconds: float, message_count: int, message_interval_seconds: float,
    ) -> Dict[str, Any]:
        """
        Run one request against a stream with the given timing.

        :param timeout_seconds: The --request-timeout cap in seconds
        :param message_count: How many messages the fake stream sends
        :param message_interval_seconds: Seconds between fake messages
        :return: A dict with the AgentRequestResult as "result" and the FakeSession that produced it as "session"
        """
        session: FakeSession = FakeSession(message_count=message_count,
                                           message_interval_seconds=message_interval_seconds)
        result: Optional[AgentRequestResult] = None
        with patch(
            "tests.load_tests.traffic.agent_request_executor.HttpServiceAgentSession",
            return_value=session,
        ), patch(
            "tests.load_tests.traffic.agent_request_executor.StreamingInputProcessor",
            FakeProcessor,
        ):
            request_settings: Dict[str, Any] = {
                "host": "localhost",
                "port": 30011,
                "agent": "music_nerd",
                "timeout_seconds": timeout_seconds,
                "idle_timeout_seconds": 60,
            }
            executor: AgentRequestExecutor = AgentRequestExecutor()
            result = executor.execute_request(request_settings, "prompt")
        run: Dict[str, Any] = {
            "result": result,
            "session": session,
        }
        return run
