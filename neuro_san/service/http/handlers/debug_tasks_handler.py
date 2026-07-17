
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

import json
import logging
import os
from http import HTTPStatus

from tornado.web import RequestHandler

from neuro_san.service.utils.server_context import ServerContext


class DebugTasksHandler(RequestHandler):
    """
    Handler class for the /debug/tasks endpoint.
    Returns a snapshot of the asyncio tasks currently living on every
    "used" AsyncioExecutor in this worker's pool. See
    ServerContext.dump_tasks_in_used_executors() for the underlying probe.

    Intended for on-demand diagnostics when the service appears wedged.
    Gated behind ENABLE_RUN_TIME_STATISTICS -- same env var that gates
    /profiler and /resources_utilization -- so it is NOT reachable in
    production by default.

    Response format is JSON. Pass ?format=text to receive the pretty
    multi-line rendering from ServerContext.format_task_dump() instead.
    """

    # pylint: disable=attribute-defined-outside-init
    def initialize(self, **kwargs):
        """
        This method is called by Tornado framework to allow
        injecting service-specific data into local handler context.
        :param kwargs: dictionary of named parameters, including:
            "server_context" - the ServerContext for this worker.
        """
        self.server_context: ServerContext = kwargs.pop("server_context")
        self.logger = logging.getLogger(self.__class__.__name__)
        self.is_enabled: bool = os.getenv("ENABLE_RUN_TIME_STATISTICS", "false").lower() == "true"

    async def get(self):
        """
        Implementation of GET request handler for the task dump.

        Query parameters:
          format=text  -- render as the human-readable multi-line format
                          from ServerContext.format_task_dump(). Any other
                          value (or omitted) yields JSON.
          timeout=<float in seconds> -- per-loop probe timeout; loops that
                          do not respond within this window are reported
                          as unresponsive rather than blocking the handler.
                          Default 2.0.
        """
        if not self.is_enabled:
            self.set_status(HTTPStatus.SERVICE_UNAVAILABLE)
            self.write("Run-time statistics collection is disabled. "
                       "To enable it, set environment variable ENABLE_RUN_TIME_STATISTICS to 'true'.")
            self.logger.info("Run-time statistics collection is disabled.")
            return

        # Parse per_loop_timeout (the best effort; fall back to the default).
        per_loop_timeout_s: float = 2.0
        raw_timeout: str = self.get_query_argument("timeout", default="")
        if raw_timeout:
            try:
                per_loop_timeout_s = float(raw_timeout)
            except ValueError:
                self.logger.info("Malformed timeout value '%s' in /debug/tasks request; using default %.1f",
                                 raw_timeout, per_loop_timeout_s)
                # Use the default.
                pass

        dump: Dict[str, Any] = self.server_context.dump_tasks_in_used_executors(
            per_loop_timeout_s=per_loop_timeout_s)

        response_format: str = self.get_query_argument("format", default="json").lower()
        if response_format == "text":
            self.set_header("Content-Type", "text/plain; charset=utf-8")
            self.write(ServerContext.format_task_dump(dump))
        else:
            self.set_header("Content-Type", "application/json")
        self.logger.info("Returned /debug/tasks dump for %d executor(s)", len(dump))
    def data_received(self, chunk):
        """
        This method is required to be implemented as part of RequestHandler subclass,
        but is not used in our case as we do not expect any data in the request body.
        """
