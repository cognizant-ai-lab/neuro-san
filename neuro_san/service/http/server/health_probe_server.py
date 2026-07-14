
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
from typing import List
from typing import Optional

import asyncio
import contextlib
import logging
import threading

import tornado.httpserver
import tornado.ioloop
import tornado.web

from leaf_common.asyncio.event_loop_factory import EventLoopFactory

from neuro_san.internals.interfaces.startable import Startable
from neuro_san.service.http.handlers.health_check_handler import HealthCheckHandler
from neuro_san.service.utils.server_context import ServerContext


class HealthProbeServer(Startable):
    """
    Runs the /, /healthz, /readyz, /livez health-probe endpoints on a
    dedicated port, in a dedicated OS thread with its own asyncio event
    loop. This isolates probe responsiveness from the main Tornado loop
    that serves streaming_chat and other request traffic -- so probes
    keep returning quickly even when the main loop is saturated by
    request work.

    The probe server binds its port with SO_REUSEPORT, so every worker
    process can bind the same port and the kernel distributes accepted
    connections across them. This matches the model used for the main
    server's port (server.bind() + server.start(N)).

    Lifecycle:
      - The instance is created before Tornado's server.start(N) fork.
      - Its start() (invoked as a Startable inside each worker, after
        fork) launches a background thread that:
          * creates a fresh asyncio event loop for itself,
          * builds a minimal Tornado Application with only the health
            handlers,
          * binds the probe port with reuse_port=True,
          * runs its IOLoop until process exit.
      - Because it's post-fork and daemon-threaded, no selector/kqueue
        state is inherited from the parent and process exit tears it
        down cleanly.

    Disabling: pass port=0 (or set AGENT_HEALTH_PROBE_PORT=0) to skip
    starting the separate server. In that case k8s / load-balancer
    probes must still hit the main port's handlers, which remain
    registered for backward compatibility.
    """

    # pylint: disable=too-many-instance-attributes
    def __init__(self,
                 port: int,
                 server_context: ServerContext,
                 forwarded_request_metadata: List[str],
                 logging_config: Dict[str, Any]):
        """
        :param port: TCP port to bind. 0 disables the probe server.
        :param server_context: The ServerContext supplying ServerStatus
                    (readiness / liveness state) to the handler.
        :param forwarded_request_metadata: Same list the main server
                    passes to HealthCheckHandler.initialize() so the
                    handler behaves identically on both ports.
        :param logging_config: Logging configuration dict, forwarded to
                    the handler's initialize().
        """
        self.port: int = port
        self.server_context: ServerContext = server_context
        self.forwarded_request_metadata: List[str] = forwarded_request_metadata
        self.logging_config: Dict[str, Any] = logging_config

        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ioloop: Optional[tornado.ioloop.IOLoop] = None

    def start(self):
        """
        Launch the probe server's background thread. Called inside each
        Tornado worker (as a Startable) after server.start(N) fork so
        each worker gets its own fresh loop and its own SO_REUSEPORT
        socket on the same probe port.

        No-op if port <= 0 (disabled).
        """
        if self.port <= 0:
            self.logger.info("HealthProbeServer disabled (port=%d)", self.port)
            return
        if self._thread is not None:
            self.logger.debug("HealthProbeServer already started; skipping")
            return

        self._thread = threading.Thread(
            target=self._run,
            name=f"HealthProbeServer-{self.port}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """
        Best-effort shutdown of the probe IOLoop. Safe to call multiple
        times. If the loop hasn't been started yet, this is a no-op.
        The daemon thread will die at process exit either way.
        """
        if self._ioloop is None:
            return
        # add_callback is thread-safe; asks the probe loop to stop itself.
        self._ioloop.add_callback(self._ioloop.stop)

    def _run(self) -> None:
        """
        Thread entry point. Owns the probe's asyncio loop for its full
        lifetime. Never returns under normal operation.
        """
        # Every thread that hosts an asyncio loop needs the loop assigned
        # to it explicitly (otherwise Tornado's IOLoop.current() would
        # fail to find one). EventLoopFactory produces the correct type
        # for the platform (SelectorEventLoop on Windows).
        loop: asyncio.AbstractEventLoop = EventLoopFactory.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        # Build the minimal app -- ONLY the health endpoints. Deliberately
        # excludes /profiler, /resources_utilization, /_debug/tasks, and
        # every /api/v1/* handler so this loop can't be starved by request work.
        app: tornado.web.Application = self.make_probe_app()

        # Bind the probe port with SO_REUSEPORT. Each worker's thread runs
        # this same code, so all workers share the port; the kernel
        # dispatches accepted connections across them.
        server: tornado.httpserver.HTTPServer = tornado.httpserver.HTTPServer(app)
        try:
            server.bind(self.port, reuse_port=True)
        except OSError as exc:
            self.logger.error("HealthProbeServer failed to bind port %d: %s",
                              self.port, exc)
            asyncio.set_event_loop(None)
            with contextlib.suppress(Exception):
                loop.close()
            return
        # start(1) attaches to the current IOLoop without forking (the
        # fork parameter only kicks in for N > 1).
        server.start(1)

        self._ioloop = tornado.ioloop.IOLoop.current()
        # Now we have really started the probe server. The thread will run until process exit.
        self.logger.info("HealthProbeServer started on port %d", self.port)
        try:
            self._ioloop.start()
        finally:
            # If start() returns (via stop()), tear the socket down. Any OSError
            # during teardown (e.g. the socket is already closed) is harmless
            # here -- shutdown is best-effort.
            with contextlib.suppress(OSError):
                server.stop()
            asyncio.set_event_loop(None)
            with contextlib.suppress(Exception):
                loop.close()

    def make_probe_app(self) -> tornado.web.Application:
        """
        Construct the Tornado Application. Same handler class as the main
        server uses on its port, initialized the same way, so probe
        responses look identical to the main port's.
        """
        server_status = self.server_context.get_server_status()
        live_data: Dict[str, Any] = {
            "forwarded_request_metadata": self.forwarded_request_metadata,
            "server_status": server_status,
            "op": "live",
            "logging_config": self.logging_config,
        }
        ready_data: Dict[str, Any] = {
            "forwarded_request_metadata": self.forwarded_request_metadata,
            "server_status": server_status,
            "op": "ready",
            "logging_config": self.logging_config,
        }
        handlers: List[Any] = [
            ("/", HealthCheckHandler, ready_data),
            ("/healthz", HealthCheckHandler, ready_data),
            ("/readyz", HealthCheckHandler, ready_data),
            ("/livez", HealthCheckHandler, live_data),
        ]
        return tornado.web.Application(handlers)
