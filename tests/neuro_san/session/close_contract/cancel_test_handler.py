
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
"""
See class comment for details.
"""
from typing import Any
from typing import Dict

import asyncio

import tornado.web


class CancelTestHandler(tornado.web.RequestHandler):
    """
    In-process streaming endpoint used to put an agent-session client into a
    precise, blocked state so a close() from another thread can be tested
    deterministically. The behavior is selected by the agent name in the URL:

    - agent ending in "prehang": never send response headers -- signal
      "request received" and then block, so the client stays awaiting headers
      (the pre-header abort window).
    - agent ending in "drip": flush headers + one message, signal "post flushed",
      then keep sending messages periodically so a blocked reader always has bytes
      arriving -- the data-flowing post-header case where the synchronous requests
      client can reliably interrupt the read on close().
    - anything else ("posthang"): flush headers plus one message, signal "post
      flushed", then go silent, so the client is post-header and blocked in its
      streaming read (used by the async client, which aborts silent reads).

    Signalling uses threading.Events (thread-safe) so the test's main thread can
    wait for the exact state before calling close(). The block awaits an
    asyncio.Event that is only set on server shutdown.
    """

    def initialize(self, control: Dict[str, Any]) -> None:
        """Receive the shared control dict (threading.Events + a hang asyncio.Event)."""
        # pylint: disable=attribute-defined-outside-init
        self.control = control

    def data_received(self, chunk):
        """Unused; the full body arrives via self.request.body."""
        return

    async def post(self, agent: str) -> None:
        """Drive the client into a pre-header or post-header blocked state, then hang."""
        if agent.endswith("prehang"):
            # Never write/flush: the client's request stays awaiting headers.
            self.control["pre_request_received"].set()
            await self.control["hang"].wait()
            return

        # Post-header: flush headers + one message so the client receives headers
        # (its _active_response is set) and consumes the first chunk.
        self.set_header("Content-Type", "application/json-lines")
        self.write('{"response": {"type": "AI", "text": "first"}}\n')
        await self.flush()
        self.control["post_flushed"].set()

        if agent.endswith("drip"):
            # Keep data flowing so a blocked reader always has bytes arriving --
            # the case where the sync requests client can interrupt the read.
            while not self.control["hang"].is_set():
                await asyncio.sleep(0.02)
                try:
                    self.write('{"response": {"type": "AI", "text": "tick"}}\n')
                    await self.flush()
                except Exception:  # pylint: disable=broad-exception-caught
                    return  # client disconnected
            return

        # "posthang": go silent after the first message.
        await self.control["hang"].wait()
