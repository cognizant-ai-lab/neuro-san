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
from functools import partial
from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterator
from typing import List
from unittest import TestCase

from tests.load_tests.traffic.request_timeout_error import RequestTimeoutError
from tests.load_tests.traffic.timed_streaming_chat import TimedStreamingChat


class TestTimedStreamingChat(TestCase):
    """Tests for TimedStreamingChat."""

    @staticmethod
    def _stream(
            message_count: int, message_interval: float, _request_dict: Dict[str, Any],
    ) -> Iterator[Dict[str, Any]]:
        """
        Stand-in for a session's streaming_chat: one message per interval.
        Bound with functools.partial to the streaming_chat signature.

        :param message_count: How many messages to yield
        :param message_interval: Seconds to sleep before each message
        :param _request_dict: The streaming_chat request, ignored
        :return: The messages
        """
        for index in range(message_count):
            time.sleep(message_interval)
            yield {"index": index}

    def _wrap(self, *, timeout: float, message_count: int, message_interval: float) -> TimedStreamingChat:
        """
        :param timeout: Cap in seconds passed to the wrapper
        :param message_count: Messages the fake stream yields
        :param message_interval: Seconds between them
        :return: A wrapper around a fake stream, started now
        """
        streaming_chat: Callable[[Dict[str, Any]], Iterator[Dict[str, Any]]] = partial(
            TestTimedStreamingChat._stream, message_count, message_interval,
        )
        return TimedStreamingChat(streaming_chat, time.perf_counter(), timeout)

    def test_passes_messages_through_and_times_the_first(self) -> None:
        """Within the cap every message is yielded unchanged and the first one is timed."""
        timed: TimedStreamingChat = self._wrap(timeout=5.0, message_count=3, message_interval=0.01)
        received: List[Dict[str, Any]] = list(timed.streaming_chat({}))
        self.assertEqual(received, [{"index": 0}, {"index": 1}, {"index": 2}])
        self.assertGreater(timed.get_time_to_first_response(), 0.0)
        self.assertLess(timed.get_time_to_first_response(), 1.0)

    def test_raises_once_past_the_cap(self) -> None:
        """A message arriving after the cap raises RequestTimeoutError and stops the stream."""
        timed: TimedStreamingChat = self._wrap(timeout=0.05, message_count=20, message_interval=0.02)
        received: List[Dict[str, Any]] = []
        with self.assertRaises(RequestTimeoutError):
            for message in timed.streaming_chat({}):
                received.append(message)
        self.assertLess(len(received), 20)

    def test_no_messages_means_zero_first_response(self) -> None:
        """An empty stream reports 0.0 for time to first response."""
        timed: TimedStreamingChat = self._wrap(timeout=5.0, message_count=0, message_interval=0.0)
        self.assertEqual(list(timed.streaming_chat({})), [])
        self.assertEqual(timed.get_time_to_first_response(), 0.0)
