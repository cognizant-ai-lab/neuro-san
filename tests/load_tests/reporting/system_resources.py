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

logger: logging.Logger = logging.getLogger(__name__)

# A whole-system snapshot: mem_pct, mem_avail_gb, cpu_pct, threads.
SysSnapshot = Dict[str, float]


class SystemResources:
    """Whole-system (not per-process) resource readings and reporting."""

    @staticmethod
    def total_threads() -> int:
        """
        Sum thread counts across all processes on the machine.

        :return: Total thread count, leaving out processes that exit or deny access
        """
        total: int = 0
        for process in psutil.process_iter(["num_threads"]):
            try:
                total += process.info.get("num_threads") or 0
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return total

    @staticmethod
    def thread_limits() -> Tuple[str, str]:
        """
        Return (per-user limit, system max) as display strings.

        :return: (per-user limit, system max); "n/a" when a value cannot be read
        """
        user_limit: str = "n/a"
        if resource is not None:
            try:
                soft_limit: int = 0
                soft_limit, _ = resource.getrlimit(resource.RLIMIT_NPROC)
                user_limit = (
                    "unlimited"
                    if soft_limit == resource.RLIM_INFINITY
                    else f"{soft_limit:,}"
                )
            except (ValueError, OSError, AttributeError):
                user_limit = "n/a"
        system_maximum: str = "n/a"
        try:
            with open(
                "/proc/sys/kernel/threads-max",
                encoding="utf-8",
            ) as file_handle:
                system_maximum = f"{int(file_handle.read().strip()):,}"
        except (OSError, ValueError):
            pass
        return user_limit, system_maximum

    @classmethod
    def snapshot(cls, cpu_interval_seconds: float = 0.1) -> SysSnapshot:
        """
        Capture a point-in-time whole-system snapshot.

        :param cpu_interval_seconds: Seconds to sample CPU usage over
        :return: mem_pct, mem_avail_gb, cpu_pct and threads
        """
        memory_stats = psutil.virtual_memory()
        return {
            "mem_pct": memory_stats.percent,
            "mem_avail_gb": memory_stats.available / (1024 ** 3),
            "cpu_pct": psutil.cpu_percent(interval=cpu_interval_seconds),
            "threads": cls.total_threads(),
        }

    @classmethod
    def log_prerun(cls) -> None:
        """Log the PRE-RUN SUMMARY system lines (RAM / CPU / threads)."""
        memory_stats = psutil.virtual_memory()
        total_gigabytes: float = memory_stats.total / (1024 ** 3)
        available_gigabytes: float = memory_stats.available / (1024 ** 3)
        core_count: int = psutil.cpu_count() or 1
        cpu_percentage: float = psutil.cpu_percent(interval=0.1)
        user_limit: str = ""
        system_maximum: str = ""
        user_limit, system_maximum = cls.thread_limits()
        logger.info(
            "  System RAM: %.1fG (%.1fG available, %.0f%% used)",
            total_gigabytes, available_gigabytes, memory_stats.percent,
        )
        logger.info(
            "  System CPU: %d cores (%.0f%% in use)",
            core_count, cpu_percentage,
        )
        logger.info(
            "  System threads: %s in use / limit %s per-user (%s max)",
            f"{cls.total_threads():,}", user_limit, system_maximum,
        )

    @classmethod
    def log_section(
            cls,
            before_snapshot: Optional[SysSnapshot],
            peak_snapshot: Optional[SysSnapshot],
            after_snapshot: Optional[SysSnapshot],
    ) -> None:
        """
        Log the aligned SYSTEM RESOURCES before/peak/after section.

        :param before_snapshot: Snapshot taken before the run, or None
        :param peak_snapshot: Peak values during the run, or None
        :param after_snapshot: Snapshot taken after the run, or None
        """
        rows: Tuple[Tuple[str, Optional[SysSnapshot]], ...] = (
            ("before", before_snapshot), ("peak", peak_snapshot), ("after", after_snapshot),
        )
        if all(snapshot is None for _, snapshot in rows):
            return
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  SYSTEM RESOURCES")
        logger.info("=" * SEPARATOR_WIDTH)
        total_gigabytes: float = psutil.virtual_memory().total / (1024 ** 3)
        core_count: int = psutil.cpu_count() or 1
        user_limit: str = ""
        system_maximum: str = ""
        user_limit, system_maximum = cls.thread_limits()
        for tag, snapshot in rows:
            if snapshot is not None and snapshot.get("mem_pct") is not None:
                cls._log_row(
                    "System memory", tag, cls._fmt_mem(snapshot, total_gigabytes),
                )
        for tag, snapshot in rows:
            if snapshot is not None and snapshot.get("cpu_pct") is not None:
                cls._log_row(
                    "System CPU", tag, cls._fmt_cpu(snapshot, core_count),
                )
        for tag, snapshot in rows:
            if snapshot is not None and snapshot.get("threads") is not None:
                cls._log_row(
                    "System threads", tag,
                    cls._fmt_threads(snapshot, tag, user_limit, system_maximum),
                )

    @staticmethod
    def _log_row(metric: str, tag: str, value: str) -> None:
        """
        Log one aligned metric row so value columns line up.

        :param metric: Metric name, e.g. "System memory"
        :param tag: "before", "peak" or "after"
        :param value: Formatted value
        """
        logger.info("  %-14s %-9s %s", metric, f"({tag}):", value)

    @staticmethod
    def _fmt_mem(snapshot: SysSnapshot, total_gigabytes: float) -> str:
        """
        Format a memory row: used / free / percent.

        :param snapshot: System snapshot
        :param total_gigabytes: Total system memory in GB
        :return: e.g. '8192M used / 7.5G free (50% used)'
        """
        memory_percentage: float = snapshot.get("mem_pct", 0.0)
        available_gigabytes: float = snapshot.get("mem_avail_gb", 0.0)
        used_megabytes: float = memory_percentage / 100.0 * total_gigabytes * 1024.0
        return (
            f"{used_megabytes:.0f}M used / {available_gigabytes:.1f}G free"
            f" ({memory_percentage:.0f}% used)"
        )

    @staticmethod
    def _fmt_cpu(snapshot: SysSnapshot, core_count: int) -> str:
        """
        Format a CPU row: percent and core-equivalents.

        :param snapshot: System snapshot
        :param core_count: Number of CPU cores
        :return: e.g. '50% (2.00 of 4 cores)'
        """
        cpu_percentage: float = snapshot.get("cpu_pct", 0.0)
        return f"{cpu_percentage:.0f}% ({cpu_percentage / 100.0 * core_count:.2f} of {core_count} cores)"

    @staticmethod
    def _fmt_threads(snapshot: SysSnapshot, tag: str, user_limit: str, system_maximum: str) -> str:
        """
        Format a threads row; limits only on the before row.

        :param snapshot: System snapshot
        :param tag: "before", "peak" or "after"
        :param user_limit: Per-user thread limit from thread_limits
        :param system_maximum: System thread max from thread_limits
        :return: e.g. '1,234 in use', with the limits added on the before row
        """
        threads: int = int(snapshot.get("threads", 0))
        if tag == "before":
            return (
                f"{threads:,} in use / limit {user_limit}"
                f" per-user ({system_maximum} max)"
            )
        return f"{threads:,} in use"
