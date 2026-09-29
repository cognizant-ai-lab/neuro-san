
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
import time
from typing import Any
from typing import Dict
from typing import Iterator
from typing import Tuple
from unittest import TestCase
from unittest.mock import patch

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.traffic.agent_request_executor import AgentRequestExecutor
from tests.load_tests.traffic.agent_request_result import AgentRequestResult


class FakeSession:
    """Stand-in for HttpServiceAgentSession that streams on a timer."""

    def __init__(self, *, message_count: int, message_interval: float, **_kwargs: Any):
        """
        Constructor.

        :param message_count: How many messages to stream
        :param message_interval: Seconds between messages
        :param _kwargs: The real session's constructor arguments, ignored
        """
        self._message_count: int = message_count
        self._message_interval: float = message_interval
        self.sent: int = 0

    def streaming_chat(self, _request_dict: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """
        Yield one message per interval, counting what was consumed.

        :param _request_dict: The streaming_chat request, ignored
        :return: One AI chat message per interval
        """
        for _ in range(self._message_count):
            time.sleep(self._message_interval)
            self.sent += 1
            yield {
                "response": {
                    "type": "AI",
                    "text": "answer",
                },
            }


class FakeProcessor:
    """Stand-in for StreamingInputProcessor that drains the stream."""

    def __init__(self, *, session: FakeSession, **_kwargs: Any):
        """
        Constructor.

        :param session: The session whose streaming_chat is consumed
        :param _kwargs: The real processor's constructor arguments, ignored
        """
        self._session: FakeSession = session

    def get_message_processor(self) -> BasicMessageProcessor:
        """
        :return: A real message processor that has seen the stream's sly_data
        """
        processor: BasicMessageProcessor = BasicMessageProcessor()
        processor.process_message({
            "type": "AGENT_FRAMEWORK", "chat_context": {},
            "sly_data": {"reservation_id": "abc-1"},
        })
        return processor

    def process_once(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Consume every streamed message, as the real processor does.

        :param state: The request state
        :return: A copy of the state with the answer filled in
        """
        for _ in self._session.streaming_chat({}):
            pass
        updated: Dict[str, Any] = dict(state)
        updated["last_chat_response"] = "answer"
        return updated


class TestAgentRequestExecutor(TestCase):
    """
    Unit tests for --request-timeout in the HTTP transport.

    A streaming request that keeps producing messages must still be
    abandoned at the cap: without that, one slow request holds a worker
    for the whole run.
    """

    def _execute(
            self, *, timeout: float, message_count: int, message_interval: float,
    ) -> Tuple[AgentRequestResult, FakeSession]:
        """
        Run one request against a stream with the given timing.

        :param timeout: The --request-timeout cap in seconds
        :param message_count: How many messages the fake stream sends
        :param message_interval: Seconds between fake messages
        :return: The AgentRequestResult and the FakeSession that produced it
        """
        session: FakeSession = FakeSession(
            message_count=message_count,
            message_interval=message_interval,
        )
        with patch(
            "tests.load_tests.traffic.agent_request_executor."
            "HttpServiceAgentSession",
            return_value=session,
        ), patch(
            "tests.load_tests.traffic.agent_request_executor."
            "StreamingInputProcessor",
            FakeProcessor,
        ):
            result: AgentRequestResult = AgentRequestExecutor.execute_request(
                "localhost", 30011, "music_nerd", "prompt",
                timeout=timeout, idle_timeout=60,
            )
        return result, session

    def test_streaming_past_the_cap_is_a_timeout(self) -> None:
        """A stream that outruns the cap reports TIMEOUT."""
        result, _session = self._execute(
            timeout=0.3, message_count=20, message_interval=0.05,
        )

        self.assertEqual(result.get_status(), STATUS_TIMEOUT)

    def test_streaming_past_the_cap_stops_early(self) -> None:
        """The request is abandoned rather than drained to the end.

        Reporting TIMEOUT after draining the whole stream would still
        label the request correctly while the worker stayed occupied,
        which is the behaviour being fixed.
        """
        start: float = time.perf_counter()
        _result, session = self._execute(
            timeout=0.3, message_count=20, message_interval=0.05,
        )
        elapsed: float = time.perf_counter() - start

        self.assertLess(session.sent, 20)
        self.assertLess(elapsed, 20 * 0.05)

    def test_request_within_the_cap_succeeds(self) -> None:
        """A request that finishes in time is unaffected."""
        result, session = self._execute(
            timeout=30, message_count=3, message_interval=0.01,
        )

        self.assertEqual(result.get_status(), STATUS_CREATED)
        self.assertEqual(result.get_response_text(), "answer")
        self.assertEqual(result.get_processor().get_sly_data().get("reservation_id"), "abc-1")
        self.assertEqual(session.sent, 3)
        self.assertGreater(result.get_time_to_first_response(), 0.0)
