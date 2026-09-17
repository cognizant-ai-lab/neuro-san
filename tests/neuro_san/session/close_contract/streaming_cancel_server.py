
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
from typing import Optional

import asyncio

from threading import Event
from threading import Thread

import tornado.httpserver
import tornado.web

from tornado.testing import bind_unused_port

from tests.neuro_san.session.close_contract.cancel_test_handler import CancelTestHandler


class StreamingCancelServer:
    """
    In-process Tornado server (run on its own thread + event loop) used by the
    close()-cancellation transport tests. It serves CancelTestHandler on
    /api/v1/<agent>/streaming_chat so a real agent session can connect and be
    driven into a blocked pre-header or post-header state.

    Runs on a dedicated thread so the test's main thread can call the session's
    synchronous close() while a client (on yet another thread) is blocked mid
    request -- exercising the cross-thread / loop-scheduled abort paths.

    Exposes threading.Events (post_flushed, pre_request_received) the test waits
    on to reach a deterministic state before calling close(), so no sleeps are
    needed.
    """

    def __init__(self):
        """Constructor."""
        self.post_flushed: Event = Event()
        self.pre_request_received: Event = Event()
        self._hang: Optional[asyncio.Event] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[tornado.httpserver.HTTPServer] = None
        self._thread: Optional[Thread] = None
        self._port: Optional[int] = None

    def start(self):
        """Bind a port and start the server on a background thread; block until ready."""
        sock, self._port = bind_unused_port()
        ready: Event = Event()
        self._thread = Thread(target=self._run, args=(ready, sock), name="StreamingCancelServer", daemon=True)
        self._thread.start()
        if not ready.wait(timeout=5.0):
            raise RuntimeError("StreamingCancelServer failed to start")

    def _run(self, ready: Event, sock):
        """Thread body: own event loop, hang Event, Tornado server, then run forever."""
        loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        # Created on this loop; awaited by handlers, only set on shutdown.
        self._hang = asyncio.Event()
        control: Dict[str, Any] = {
            "post_flushed": self.post_flushed,
            "pre_request_received": self.pre_request_received,
            "hang": self._hang,
        }
        app: tornado.web.Application = tornado.web.Application(
            [(r"/api/v1/(.+)/streaming_chat", CancelTestHandler, {"control": control})])
        self._server = tornado.httpserver.HTTPServer(app)
        self._server.add_socket(sock)
        loop.call_soon(ready.set)
        loop.run_forever()

    @property
    def base_url(self) -> str:
        """:return: The base http URL of the running server."""
        return f"http://127.0.0.1:{self._port}"

    @property
    def port(self) -> str:
        """:return: The bound port as a string (as agent sessions expect)."""
        return str(self._port)

    def _shutdown(self):
        """Runs on the server loop: release hung handlers, stop the server and loop."""
        self._hang.set()
        self._server.stop()
        self._loop.stop()

    def stop(self):
        """Stop the server and join its thread. Safe if never started."""
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._shutdown)
        self._thread.join(timeout=5.0)
