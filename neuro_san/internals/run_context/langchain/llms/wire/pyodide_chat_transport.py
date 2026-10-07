
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

from json import dumps

from neuro_san.internals.run_context.langchain.llms.wire.chat_transport import ChatTransport


class PyodideChatTransport(ChatTransport):
    """
    ChatTransport over the browser's own fetch(), for running under Pyodide.

    Pyodide has no TCP sockets, so neither httpx nor aiohttp can reach the
    network from it: everything goes through JavaScript's fetch(). This asks
    for it directly rather than tunnelling an HTTP client over it, which is
    also what the hand-written JavaScript runtime does.

    fetch() hands back a byte stream with no notion of lines, so the line
    splitting aiohttp does for free is done here instead. That is the whole
    difference between the two transports.

    UNVERIFIED: this cannot be exercised outside a browser, and has not been
    run under Pyodide. The wire format and SSE handling above it are covered
    by tests through AiohttpChatTransport; what is untested here is exactly
    this file.
    """

    # Imported lazily inside the methods: the module only exists under Pyodide,
    # so importing it at module scope would break every other runtime, this
    # repo's test suite included.

    def __init__(self, chunk_encoding: str = "utf-8"):
        """
        Constructor

        :param chunk_encoding: The encoding to decode response bytes with
        """
        self.chunk_encoding: str = chunk_encoding

    async def stream_lines(self, url: str, headers: Dict[str, str],
                           body: Dict[str, Any]) -> AsyncIterator[str]:
        """
        POST a JSON body through the browser's fetch() and yield text lines.

        :param url: The full URL to POST to
        :param headers: Headers to send
        :param body: The JSON-serialisable request body
        :return: An async iterator over the response's text lines
        """
        # pylint: disable=import-outside-toplevel,import-error
        from pyodide.http import pyfetch

        response = await pyfetch(url, method="POST", headers=headers, body=dumps(body))
        if response.status >= 400:
            detail: str = await response.string()
            raise ValueError(f"LLM HTTP {response.status}: {detail[:300]}")

        reader = response.js_response.body.getReader()
        buffer: str = ""
        while True:
            chunk = await reader.read()
            if chunk.done:
                break
            buffer += bytes(chunk.value.to_py()).decode(self.chunk_encoding)
            # Yield only whole lines; a chunk boundary can fall mid-line, so
            # whatever follows the last newline stays buffered for the next one.
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                yield line.rstrip("\r")

        # A stream that ends without a trailing newline still has a last line.
        if buffer:
            yield buffer.rstrip("\r")
