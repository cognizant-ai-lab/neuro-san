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

"""Shared whole-system resource snapshots and reporting.

Centralizes the whole-machine (not per-process) memory, CPU, and
thread readings so the PRE-RUN SUMMARY and the OVERALL SYSTEM
RESOURCES section render from a single source instead of duplicated
copies across the input validator, load test, and summary reporter.
"""

import logging
from typing import Dict
from typing import Optional
from typing import Tuple

try:
    import resource
except ImportError:
    # Unix-only module.  Thread limits report "n/a" without it.
    resource = None

import psutil

from tests.load_tests.config import SEPARATOR_WIDTH

logger = logging.getLogger(__name__)

# A whole-system snapshot: mem_pct, mem_avail_gb, cpu_pct, threads.
SysSnapshot = Dict[str, float]


class SystemResources:
    """Whole-system (not per-process) resource readings and reporting."""

    @staticmethod
    def total_threads() -> int:
        """Sum thread counts across all processes on the machine."""
        total = 0
        for proc in psutil.process_iter(["num_threads"]):
            try:
                total += proc.info["num_threads"] or 0
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return total

    @staticmethod
    def thread_limits() -> Tuple[str, str]:
        """Return (per-user limit, system max) as display strings."""
        user_limit = "n/a"
        if resource is not None:
            try:
                soft, _ = resource.getrlimit(resource.RLIMIT_NPROC)
                user_limit = (
                    "unlimited"
                    if soft == resource.RLIM_INFINITY
                    else f"{soft:,}"
                )
            except (ValueError, OSError, AttributeError):
                user_limit = "n/a"
        sys_max = "n/a"
        try:
            with open(
                "/proc/sys/kernel/threads-max",
                encoding="utf-8",
            ) as handle:
                sys_max = f"{int(handle.read().strip()):,}"
        except (OSError, ValueError):
            pass
        return user_limit, sys_max

    @classmethod
    def snapshot(cls, *, cpu_interval: float = 0.1) -> SysSnapshot:
        """Capture a point-in-time whole-system snapshot."""
        mem = psutil.virtual_memory()
        return {
            "mem_pct": mem.percent,
            "mem_avail_gb": mem.available / (1024 ** 3),
            "cpu_pct": psutil.cpu_percent(interval=cpu_interval),
            "threads": cls.total_threads(),
        }

    @classmethod
    def log_prerun(cls) -> None:
        """Log the PRE-RUN SUMMARY system lines (RAM / CPU / threads)."""
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024 ** 3)
        avail_gb = mem.available / (1024 ** 3)
        ncores = psutil.cpu_count() or 1
        cpu_pct = psutil.cpu_percent(interval=0.1)
        user_limit, sys_max = cls.thread_limits()
        logger.info(
            "  System RAM: %.1fG (%.1fG available, %.0f%% used)",
            total_gb, avail_gb, mem.percent,
        )
        logger.info(
            "  System CPU: %d cores (%.0f%% in use)",
            ncores, cpu_pct,
        )
        logger.info(
            "  System threads: %s in use / limit %s per-user (%s max)",
            f"{cls.total_threads():,}", user_limit, sys_max,
        )

    @classmethod
    def log_section(
            cls,
            before: Optional[SysSnapshot],
            peak: Optional[SysSnapshot],
            after: Optional[SysSnapshot],
    ) -> None:
        """Log the aligned SYSTEM RESOURCES before/peak/after section."""
        rows = (("before", before), ("peak", peak), ("after", after))
        if all(snap is None for _, snap in rows):
            return
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  SYSTEM RESOURCES")
        logger.info("=" * SEPARATOR_WIDTH)
        total_gb = psutil.virtual_memory().total / (1024 ** 3)
        ncores = psutil.cpu_count() or 1
        user_limit, sys_max = cls.thread_limits()
        for tag, snap in rows:
            if snap is not None and snap.get("mem_pct") is not None:
                cls._log_row(
                    "System memory", tag, cls._fmt_mem(snap, total_gb),
                )
        for tag, snap in rows:
            if snap is not None and snap.get("cpu_pct") is not None:
                cls._log_row(
                    "System CPU", tag, cls._fmt_cpu(snap, ncores),
                )
        for tag, snap in rows:
            if snap is not None and snap.get("threads") is not None:
                cls._log_row(
                    "System threads", tag,
                    cls._fmt_threads(snap, tag, user_limit, sys_max),
                )

    @staticmethod
    def _log_row(metric: str, tag: str, value: str) -> None:
        """Log one aligned metric row so value columns line up."""
        logger.info("  %-14s %-9s %s", metric, f"({tag}):", value)

    @staticmethod
    def _fmt_mem(snap: SysSnapshot, total_gb: float) -> str:
        """Format a memory row: used / free / percent."""
        pct = snap["mem_pct"]
        avail_gb = snap.get("mem_avail_gb", 0.0)
        used_mb = pct / 100.0 * total_gb * 1024.0
        return (
            f"{used_mb:.0f}M used / {avail_gb:.1f}G free"
            f" ({pct:.0f}% used)"
        )

    @staticmethod
    def _fmt_cpu(snap: SysSnapshot, ncores: int) -> str:
        """Format a CPU row: percent and core-equivalents."""
        pct = snap["cpu_pct"]
        return f"{pct:.0f}% ({pct / 100.0 * ncores:.2f} of {ncores} cores)"

    @staticmethod
    def _fmt_threads(
            snap: SysSnapshot, tag: str,
            user_limit: str, sys_max: str,
    ) -> str:
        """Format a threads row; limits only on the before row."""
        threads = int(snap["threads"])
        if tag == "before":
            return (
                f"{threads:,} in use / limit {user_limit}"
                f" per-user ({sys_max} max)"
            )
        return f"{threads:,} in use"
