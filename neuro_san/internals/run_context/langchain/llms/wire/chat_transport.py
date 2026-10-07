
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


class ChatTransport:
    """
    Interface for issuing one streaming chat request and handing back its
    response body as text lines.

    Exists so the chat model above it can be written once and run wherever the
    host can make an HTTP request. What differs between a CPython process and a
    browser is only how bytes are fetched and decoded, so that is all this
    covers: the wire format, the SSE framing and everything above it belong to
    the caller.

    Lines rather than bytes because every consumer of a chat completions stream
    wants lines, and the buffering needed to produce them is exactly the part
    that differs per platform.
    """

    async def stream_lines(self, url: str, headers: Dict[str, str],
                           body: Dict[str, Any]) -> AsyncIterator[str]:
        """
        POST a JSON body and yield the response body as decoded text lines.

        :param url: The full URL to POST to
        :param headers: Headers to send
        :param body: The JSON-serialisable request body
        :return: An async iterator over the response's text lines, without
                 their line terminators
        """
        raise NotImplementedError

    async def aclose(self) -> None:
        """
        Release anything this transport holds. Safe to call more than once.
        """
