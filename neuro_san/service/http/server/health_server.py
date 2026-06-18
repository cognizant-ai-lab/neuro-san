
# Copyright (C) 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
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
Dedicated health check server that runs on a separate port and thread
so that Kubernetes liveness/readiness probes are never blocked by
heavy request processing on the main event loop.
"""

import asyncio
import logging
import threading

import tornado.httpserver
import tornado.ioloop
import tornado.web

from neuro_san.service.http.handlers.health_check_handler import HealthCheckHandler
from neuro_san.service.utils.server_status import ServerStatus

logger = logging.getLogger(__name__)


class HealthServer:
    """
    A lightweight HTTP server dedicated to serving health check endpoints
    (/livez, /readyz) on a separate port in its own thread. This prevents
    Kubernetes probes from being starved when the main application event
    loop is saturated with long-running LLM requests.
    """

    def __init__(self, port: int, server_status: ServerStatus):
        """
        :param port: TCP port for the dedicated health server
        :param server_status: ServerStatus instance to query for readiness/liveness
        """
        self.port = port
        self.server_status = server_status
        self._thread: threading.Thread = None

    def start(self):
        """
        Start the health check server in a daemon thread.
        """
        self._thread = threading.Thread(
            target=self._run,
            name="health-server",
            daemon=True
        )
        self._thread.start()
        logger.info("Health check server started on port %d", self.port)

    def _run(self):
        """
        Entry point for the health server thread. Creates its own
        asyncio event loop and Tornado IOLoop so it is fully independent
        of the main application event loop.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        forwarded_request_metadata = []
        logging_config = {}

        live_data = {
            "forwarded_request_metadata": forwarded_request_metadata,
            "server_status": self.server_status,
            "op": "live",
            "logging_config": logging_config
        }
        ready_data = {
            "forwarded_request_metadata": forwarded_request_metadata,
            "server_status": self.server_status,
            "op": "ready",
            "logging_config": logging_config
        }

        app = tornado.web.Application([
            ("/", HealthCheckHandler, ready_data),
            ("/livez", HealthCheckHandler, live_data),
            ("/readyz", HealthCheckHandler, ready_data),
        ])

        server = tornado.httpserver.HTTPServer(app)
        server.listen(self.port)
        tornado.ioloop.IOLoop.current().start()
