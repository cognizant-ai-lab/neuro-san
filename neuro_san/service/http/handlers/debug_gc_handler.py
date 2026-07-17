
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

import gc
import json
import logging
import os
import time
from http import HTTPStatus

import psutil

from tornado.web import RequestHandler


class DebugGcHandler(RequestHandler):
    """
    Handler class for the /debug/gc endpoint.

    Forces a full Python garbage collection sweep (all generations) in the
    worker process that handles the request. Reports:

      - Number of objects collected across all generations.
      - Duration of the collection in milliseconds.
      - Process memory (RSS and VMS) before and after the sweep, plus the
        RSS delta (negative = memory freed).

    Response format is JSON. Pass ?format=text for a human-readable rendering.

    Gated behind ENABLE_RUN_TIME_STATISTICS -- same env var that gates
    /debug/tasks, /profiler and /resources_utilization -- so it is NOT
    reachable in production by default.

    Multi-worker note: gc.collect() is process-local. When neuro-san runs
    with multiple Tornado worker processes (AGENT_HTTP_SERVER_INSTANCES > 1),
    each call to this endpoint only forces GC in the ONE worker that
    handled the request. The kernel routes accepted connections across
    workers, so probing every worker requires several sequential calls (or
    per-worker port access).

    Diagnostic-only note: gc.collect() holds the GIL for its entire
    duration, pausing every thread in this worker. Typical durations on a
    healthy process are < 100 ms; loaded processes with many live objects
    can push into seconds. Do not call this repeatedly on a busy production
    server.
    """

    # pylint: disable=attribute-defined-outside-init
    def initialize(self, **_kwargs):
        """
        This method is called by Tornado framework to allow injecting
        service-specific data into local handler context. No injected
        state is required here -- the handler operates on the worker's
        own process.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.is_enabled: bool = os.getenv("ENABLE_RUN_TIME_STATISTICS", "false").lower() == "true"

    async def get(self):
        """
        Implementation of GET request handler for the /debug/gc endpoint.

        Query parameters:
          format=text  -- render as a human-readable multi-line report.
                          Any other value (or omitted) yields JSON.
        """
        if not self.is_enabled:
            self.set_status(HTTPStatus.SERVICE_UNAVAILABLE)
            self.write("Run-time statistics collection is disabled. "
                       "To enable it, set environment variable ENABLE_RUN_TIME_STATISTICS to 'true'.")
            self.logger.info("Run-time statistics collection is disabled.")
            return

        report: Dict[str, Any] = self._force_gc_and_measure()

        response_format: str = self.get_query_argument("format", default="json").lower()
        if response_format == "text":
            self.set_header("Content-Type", "text/plain; charset=utf-8")
            self.write(self._format_report(report))
        else:
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps(report, indent=2))

        rss_delta_mb: float = report["memory"]["rss_delta_bytes"] / (1024 * 1024)
        self.logger.info(
            "/debug/gc collected=%d duration=%.1fms rss_delta=%+.2fMB (pid=%d)",
            report["collected"], report["duration_ms"], rss_delta_mb, report["pid"])

    @staticmethod
    def _force_gc_and_measure() -> Dict[str, Any]:
        """
        Sample process memory, run gc.collect(), re-sample,
        and return the structured report.

        Kept as a static helper so the mechanics are testable independent
        of Tornado / HTTP plumbing.
        """
        pid: int = os.getpid()
        process: psutil.Process = psutil.Process(pid)

        mem_before = process.memory_info()

        start: float = time.monotonic()
        collected: int = gc.collect()
        duration_ms: float = (time.monotonic() - start) * 1000.0

        mem_after = process.memory_info()

        return {
            "pid": pid,
            "collected": collected,
            "duration_ms": round(duration_ms, 3),
            "memory": {
                "rss_before_bytes": mem_before.rss,
                "rss_after_bytes": mem_after.rss,
                "rss_delta_bytes": mem_after.rss - mem_before.rss,
                "vms_before_bytes": mem_before.vms,
                "vms_after_bytes": mem_after.vms,
            }
        }

    @staticmethod
    def _format_report(report: Dict[str, Any]) -> str:
        """
        Render the report dict as a printable multi-line string.
        """
        mem = report["memory"]

        def _mb(n: int) -> str:
            return f"{n / (1024 * 1024):.2f} MB"

        lines: List[str] = [
            f"pid            : {report['pid']}",
            f"collected      : {report['collected']}",
            f"duration       : {report['duration_ms']:.3f} ms",
            "",
            "memory:",
            f"  rss  before  : {_mb(mem['rss_before_bytes'])}",
            f"  rss  after   : {_mb(mem['rss_after_bytes'])}",
            f"  rss  delta   : {_mb(mem['rss_delta_bytes']):>10} "
            f"({'+' if mem['rss_delta_bytes'] >= 0 else ''}{mem['rss_delta_bytes']:,} bytes)",
            f"  vms  before  : {_mb(mem['vms_before_bytes'])}",
            f"  vms  after   : {_mb(mem['vms_after_bytes'])}",
            "",
        ]
        return "\n".join(lines)

    def data_received(self, chunk):
        """
        This method is required to be implemented as part of RequestHandler subclass,
        but is not used in our case as we do not expect any data in the request body.
        """
