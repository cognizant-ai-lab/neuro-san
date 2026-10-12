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
from typing import Callable
from typing import Dict
from typing import Iterator
from typing import Optional

from tests.load_tests.traffic.request_timeout_error import RequestTimeoutError


class TimedStreamingChat:
    """
    Wraps a session's streaming_chat to time the first streamed message
    and to abandon the stream once --request-timeout has elapsed.

    The check happens per streamed message, so a request is abandoned within
    one message of the cap rather than exactly at it; the wait for a message
    is bounded separately by the session's idle timeout.
    """

    def __init__(
            self,
            streaming_chat: Callable[[Dict[str, Any]], Iterator[Dict[str, Any]]],
            start_seconds: float,
            timeout_seconds: float,
    ) -> None:
        """
        Constructor.

        :param streaming_chat: The session's own streaming_chat to wrap
        :param start_seconds: time.perf_counter() value taken when the request started
        :param timeout_seconds: Cap in seconds on the whole request (--request-timeout)
        """
        self._streaming_chat: Callable[[Dict[str, Any]], Iterator[Dict[str, Any]]] = streaming_chat
        self._start_seconds: float = start_seconds
        self._timeout_seconds: float = timeout_seconds
        self._time_to_first_response_seconds: Optional[float] = None

    def streaming_chat(self, request_dict: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """
        Drop-in for the session's streaming_chat.

        :param request_dict: The streaming_chat request
        :return: The wrapped session's chat responses, unchanged
        :raises RequestTimeoutError: When a message arrives after the cap
        """
        for chat_response in self._streaming_chat(request_dict):
            elapsed_seconds: float = time.perf_counter() - self._start_seconds
            if self._time_to_first_response_seconds is None:
                self._time_to_first_response_seconds = elapsed_seconds
            if elapsed_seconds >= self._timeout_seconds:
                raise RequestTimeoutError()
            yield chat_response

    def get_time_to_first_response(self) -> float:
        """
        Report when the first streamed message arrived.

        :return: Seconds from start to the first streamed message; 0.0 when none arrived
        """
        if self._time_to_first_response_seconds is None:
            return 0.0
        return self._time_to_first_response_seconds
