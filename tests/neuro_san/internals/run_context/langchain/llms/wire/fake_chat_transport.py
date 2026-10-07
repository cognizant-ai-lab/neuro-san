
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
"""
See class comment for details.
"""

from typing import Any
from typing import AsyncIterator
from typing import Dict
from typing import List

from neuro_san.internals.run_context.langchain.llms.wire.chat_transport import ChatTransport


class FakeChatTransport(ChatTransport):
    """
    A ChatTransport that replays canned lines instead of making a request.

    Lets the wire format, the SSE framing and the tool-call assembly above it
    be tested without a server or a network, and lets a test present awkward
    framing on purpose -- a tool call split mid-argument, a stray keep-alive,
    a chunk boundary in the wrong place -- which a real endpoint will not do
    on demand.
    """

    def __init__(self, lines: List[str]):
        """
        Constructor

        :param lines: The response body lines to replay, in order
        """
        self.lines: List[str] = lines
        self.requests: List[Dict[str, Any]] = []
        self.closed: bool = False

    async def stream_lines(self, url: str, headers: Dict[str, str],
                           body: Dict[str, Any]) -> AsyncIterator[str]:
        """
        Record the request and replay the canned lines.

        :param url: The URL that would have been posted to
        :param headers: The headers that would have been sent
        :param body: The body that would have been sent
        :return: An async iterator over the canned lines
        """
        self.requests.append({"url": url, "headers": headers, "body": body})
        for line in self.lines:
            yield line

    async def aclose(self) -> None:
        """
        Record that the transport was closed.
        """
        self.closed = True
