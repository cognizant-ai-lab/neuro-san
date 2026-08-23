
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
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.traffic.http_client import HttpClient


class FakeSession:
    """Stand-in for HttpServiceAgentSession that streams on a timer."""

    def __init__(self, *, message_count, message_interval, **_kwargs):
        """Stream ``message_count`` messages, one per interval."""
        self._message_count = message_count
        self._message_interval = message_interval
        self.sent = 0

    def streaming_chat(self, _request_dict):
        """Yield one message per interval, counting what was consumed."""
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

    def __init__(self, *, session, **_kwargs):
        """Keep the session whose streaming_chat is consumed."""
        self._session = session

    def process_once(self, state):
        """Consume every streamed message, as the real processor does."""
        for _ in self._session.streaming_chat({}):
            pass
        updated = dict(state)
        updated["last_chat_response"] = "answer"
        updated["returned_sly_data"] = {"reservation_id": "abc-1"}
        return updated


class TestHttpRequestTimeout(TestCase):
    """
    Unit tests for --request-timeout in the HTTP transport.

    A streaming request that keeps producing messages must still be
    abandoned at the cap: without that, one slow request holds a worker
    for the whole run and the timeout only describes subprocess mode.
    """

    def _execute(self, *, timeout, message_count, message_interval):
        """Run one request against a stream with the given timing."""
        session = FakeSession(
            message_count=message_count,
            message_interval=message_interval,
        )
        with patch(
            "tests.load_tests.traffic.http_client."
            "HttpServiceAgentSession",
            return_value=session,
        ), patch(
            "tests.load_tests.traffic.http_client."
            "StreamingInputProcessor",
            FakeProcessor,
        ):
            result = HttpClient.execute_request(
                "localhost", 30011, "music_nerd", "prompt",
                timeout=timeout, idle_timeout=60,
            )
        return result, session

    def test_streaming_past_the_cap_is_a_timeout(self):
        """A stream that outruns the cap reports TIMEOUT."""
        (status, _fields, _text, _ttft, _tokens), _session = self._execute(
            timeout=0.3, message_count=20, message_interval=0.05,
        )

        self.assertEqual(status, STATUS_TIMEOUT)

    def test_streaming_past_the_cap_stops_early(self):
        """The request is abandoned rather than drained to the end.

        Reporting TIMEOUT after draining the whole stream would still
        label the request correctly while the worker stayed occupied,
        which is the behaviour being fixed.
        """
        start = time.time()
        _result, session = self._execute(
            timeout=0.3, message_count=20, message_interval=0.05,
        )
        elapsed = time.time() - start

        self.assertLess(session.sent, 20)
        self.assertLess(elapsed, 20 * 0.05)

    def test_request_within_the_cap_succeeds(self):
        """A request that finishes in time is unaffected."""
        (status, fields, text, ttft, _tokens), session = self._execute(
            timeout=30, message_count=3, message_interval=0.01,
        )

        self.assertEqual(status, STATUS_CREATED)
        self.assertEqual(text, "answer")
        self.assertEqual(fields.get("reservation_id"), "abc-1")
        self.assertEqual(session.sent, 3)
        self.assertGreater(ttft, 0.0)
