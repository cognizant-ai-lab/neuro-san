
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

from aiohttp import ClientSession
from aiohttp import ClientTimeout

from neuro_san.internals.run_context.langchain.llms.wire.chat_transport import ChatTransport


class AiohttpChatTransport(ChatTransport):
    """
    ChatTransport over aiohttp, for running on CPython.

    The counterpart to PyodideChatTransport, and the one every test uses: a
    browser transport cannot be exercised outside a browser, so the wire format
    and SSE handling above it are proven here instead.
    """

    def __init__(self, timeout_in_seconds: float = None):
        """
        Constructor

        :param timeout_in_seconds: Total time to allow the request, or None to
                        wait indefinitely. A streaming chat can legitimately
                        run for minutes, so there is no default deadline.
        """
        self.timeout_in_seconds: float = timeout_in_seconds
        self.session: ClientSession = None

    async def stream_lines(self, url: str, headers: Dict[str, str],
                           body: Dict[str, Any]) -> AsyncIterator[str]:
        """
        POST a JSON body and yield the response body as decoded text lines.

        :param url: The full URL to POST to
        :param headers: Headers to send
        :param body: The JSON-serialisable request body
        :return: An async iterator over the response's text lines
        """
        if self.session is None:
            self.session = ClientSession(timeout=ClientTimeout(total=self.timeout_in_seconds))

        async with self.session.post(url, json=body, headers=headers) as response:
            if response.status >= 400:
                detail: str = await response.text()
                raise ValueError(f"LLM HTTP {response.status}: {detail[:300]}")
            # aiohttp splits the body on newlines for us, which is the one
            # thing a browser's fetch() will not do.
            async for raw_line in response.content:
                yield raw_line.decode("utf-8").rstrip("\r\n")

    async def aclose(self) -> None:
        """
        Close the underlying session. Safe to call more than once.
        """
        if self.session is not None:
            session: ClientSession = self.session
            self.session = None
            await session.close()
