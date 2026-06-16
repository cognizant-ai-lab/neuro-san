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

"""Resource monitoring — psutil-based process snapshots.

Interim implementation. May be replaced by neuro-san built-in
monitoring and telemetry when those features become available.
"""

import logging
from typing import Optional

import psutil

from tests.load_tests.config import ResourceSnapshot

logger = logging.getLogger(__name__)


class ResourceMonitor:
    """Captures and logs psutil-based process resource snapshots."""

    @staticmethod
    def find_process(keyword) -> Optional[psutil.Process]:
        """Find a running process whose command line contains the given keyword."""
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if keyword in cmdline:
                    return psutil.Process(proc.info.get("pid"))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def find_process_by_port(port) -> Optional[psutil.Process]:
        """Find a process listening on the given port."""
        for proc in psutil.process_iter(["pid"]):
            try:
                for conn in proc.net_connections():
                    if conn.status == "LISTEN" and conn.laddr.port == port:
                        return psutil.Process(proc.info.get("pid"))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def snapshot(proc) -> Optional[ResourceSnapshot]:
        """Capture a point-in-time resource snapshot of a process."""
        if proc is None:
            return None
        try:
            mem = proc.memory_info()
            try:
                fds = proc.num_fds()
            except AttributeError:
                fds = proc.num_handles()
            return {
                "rss": mem.rss / 1024 / 1024,
                "fds": fds,
                "threads": proc.num_threads(),
                "connections": len(proc.net_connections()),
                "children": len(proc.children()),
                "cpu": proc.cpu_percent(interval=0.1),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    @staticmethod
    def log_snapshot(label, snap) -> None:
        """Log a single resource snapshot."""
        if snap is None:
            logger.info("  %s: process not found", label)
            return
        logger.info(
            "  %s: RSS=%.1f MB, FDs=%s, Threads=%s, Conns=%s, CPU=%.1f%%, Children=%s",
            label, snap.get("rss"), snap.get("fds"), snap.get("threads"),
            snap.get("connections"), snap.get("cpu"), snap.get("children"),
        )
