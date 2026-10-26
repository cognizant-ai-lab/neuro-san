
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

from time import sleep
from typing import Any
from typing import Dict
from typing import Iterator


class FakeSession:
    """
    Stand-in for HttpServiceAgentSession that streams on a timer.
    """

    def __init__(self, message_count: int, message_interval_seconds: float, **_kwargs: Any) -> None:
        """
        Constructor.

        :param message_count: How many messages to stream
        :param message_interval_seconds: Seconds between messages
        :param _kwargs: The real session's constructor arguments, ignored
        """
        self._message_count: int = message_count
        self._message_interval_seconds: float = message_interval_seconds
        self.sent: int = 0

    def streaming_chat(self, _request_dict: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """
        Yield one message per interval, counting what was consumed.

        :param _request_dict: The streaming_chat request, ignored
        :return: One AI chat message per interval
        """
        _: int
        # Yield one message per interval, counting each one sent.
        for _ in range(self._message_count):
            sleep(self._message_interval_seconds)
            self.sent += 1
            yield {"response": {"type": "AI", "text": "answer"}}
