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

from logging import Logger
from logging import getLogger
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

try:
    import resource
except ImportError:
    # Unix-only module.  Thread limits report "n/a" without it.
    resource = None

from psutil import AccessDenied
from psutil import NoSuchProcess
from psutil import Process
from psutil import cpu_count
from psutil import cpu_percent
from psutil import process_iter
from psutil import virtual_memory

from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.reporting.formatters import Formatters

# A whole-system snapshot, with these keys:
#   "memory_percent": system memory in use, in percent
#   "available_gigabytes": system memory still available, in GB
#   "cpu_percent": system CPU use over all cores, in percent
#   "threads": number of threads running on the system
# SummaryReporter builds snapshots from stage summaries, so a value is None when a summary lacks it.
SystemSnapshot = Dict[str, Optional[float]]


class SystemResources:
    """
    Whole-system (not per-process) resource readings and reporting.

    Centralizes the whole-machine memory, CPU, and thread readings so the
    PRE-RUN SUMMARY and the OVERALL SYSTEM RESOURCES section render from a
    single source instead of duplicated copies across the input validator,
    load test, and summary reporter.
    """

    def __init__(self) -> None:
        """
        Constructor.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    @staticmethod
    def total_threads() -> int:
        """
        Sum thread counts across all processes on the machine.

        :return: Total thread count, leaving out processes that exit or deny access
        """
        total: int = 0
        process: Process
        # Add up the thread count of each process that still exists and allows access.
        for process in process_iter(["num_threads"]):
            try:
                total += process.info.get("num_threads") or 0
            except (NoSuchProcess, AccessDenied):
                continue
        return total

    @staticmethod
    def thread_limits() -> List[str]:
        """
        Return [per-user limit, system max] as display strings.

        :return: [per-user limit, system max]; "n/a" when a value cannot be read
        """
        user_limit: str = "n/a"
        if resource is not None:
            try:
                soft_limit: int = 0
                soft_limit, _ = resource.getrlimit(resource.RLIMIT_NPROC)
                if soft_limit == resource.RLIM_INFINITY:
                    user_limit = "unlimited"
                else:
                    user_limit = f"{soft_limit:,}"
            except (ValueError, OSError, AttributeError):
                user_limit = "n/a"
        system_maximum: str = "n/a"
        try:
            with open("/proc/sys/kernel/threads-max", encoding="utf-8") as file_handle:
                threads_max_text: str = file_handle.read().strip()
                threads_max: int = int(threads_max_text)
                system_maximum = f"{threads_max:,}"
        except (OSError, ValueError):
            pass
        limits: List[str] = [user_limit, system_maximum]
        return limits

    @classmethod
    def snapshot(cls, cpu_interval_seconds: float = 0.1) -> SystemSnapshot:
        """
        Capture a point-in-time whole-system snapshot.

        :param cpu_interval_seconds: Seconds to sample CPU usage over
        :return: A dictionary with these keys:
            "memory_percent": system memory in use, in percent
            "available_gigabytes": system memory still available, in GB
            "cpu_percent": system CPU use over all cores, in percent, sampled over cpu_interval_seconds
            "threads": number of threads running on the system
        """
        # psutil.virtual_memory() returns psutil's private svmem named tuple, which has no public type to name.
        memory_stats: Any = virtual_memory()
        available_gigabytes: float = memory_stats.available / ResourceMonitor.ONE_GIGABYTE
        cpu_percentage: float = cpu_percent(interval=cpu_interval_seconds)
        thread_count: int = cls.total_threads()
        system_snapshot: SystemSnapshot = {
            "memory_percent": memory_stats.percent,
            "available_gigabytes": available_gigabytes,
            "cpu_percent": cpu_percentage,
            "threads": thread_count,
        }
        return system_snapshot

    @staticmethod
    def total_gigabytes() -> float:
        """
        Read the total system memory.

        :return: Total system memory in gigabytes
        """
        # psutil.virtual_memory() returns psutil's private svmem named tuple, which has no public type to name.
        memory_stats: Any = virtual_memory()
        total_gigabytes: float = memory_stats.total / ResourceMonitor.ONE_GIGABYTE
        return total_gigabytes

    def log_prerun(self) -> None:
        """
        Log the PRE-RUN SUMMARY system lines (RAM / CPU / threads).
        """
        # psutil.virtual_memory() returns psutil's private svmem named tuple, which has no public type to name.
        memory_stats: Any = virtual_memory()
        total_gigabytes: float = memory_stats.total / ResourceMonitor.ONE_GIGABYTE
        available_gigabytes: float = memory_stats.available / ResourceMonitor.ONE_GIGABYTE
        core_count: int = cpu_count() or 1
        cpu_percentage: float = cpu_percent(interval=0.1)
        user_limit: str = ""
        system_maximum: str = ""
        user_limit, system_maximum = SystemResources.thread_limits()
        self.logger.info(
            "  System RAM: %.1f GB (%.1f GB available, %.0f%% used)",
            total_gigabytes, available_gigabytes, memory_stats.percent,
        )
        self.logger.info("  System CPU: %d cores (%.0f%% in use)", core_count, cpu_percentage)
        thread_count: int = SystemResources.total_threads()
        thread_count_text: str = f"{thread_count:,}"
        self.logger.info(
            "  System threads: %s in use / limit %s per-user (%s max)",
            thread_count_text, user_limit, system_maximum,
        )

    def log_section(
            self,
            before_snapshot: Optional[SystemSnapshot],
            peak_snapshot: Optional[SystemSnapshot],
            after_snapshot: Optional[SystemSnapshot],
    ) -> None:
        """
        Log the aligned SYSTEM RESOURCES before/peak/after section.

        :param before_snapshot: Snapshot taken before the run, or None
        :param peak_snapshot: Peak values during the run, or None
        :param after_snapshot: Snapshot taken after the run, or None
        """
        snapshots_by_tag: Dict[str, Optional[SystemSnapshot]] = {
            "before": before_snapshot,
            "peak": peak_snapshot,
            "after": after_snapshot,
        }
        has_snapshot: bool = False
        tag: str
        snapshot: Optional[SystemSnapshot]
        # Look for at least one snapshot that is set.
        for tag, snapshot in snapshots_by_tag.items():
            if snapshot is not None:
                has_snapshot = True
                break
        if not has_snapshot:
            return
        self.logger.info("\n%s", Formatters.SEPARATOR_LINE)
        self.logger.info("  SYSTEM RESOURCES")
        self.logger.info("%s", Formatters.SEPARATOR_LINE)
        total_gigabytes: float = SystemResources.total_gigabytes()
        core_count: int = cpu_count() or 1
        user_limit: str = ""
        system_maximum: str = ""
        user_limit, system_maximum = SystemResources.thread_limits()
        row_text: str = ""
        # One memory row per snapshot that has it.
        for tag, snapshot in snapshots_by_tag.items():
            if snapshot is not None and snapshot.get("memory_percent") is not None:
                row_text = SystemResources._format_memory_row(snapshot, total_gigabytes)
                self._log_row("System memory", tag, row_text)
        # One CPU row per snapshot that has it.
        for tag, snapshot in snapshots_by_tag.items():
            if snapshot is not None and snapshot.get("cpu_percent") is not None:
                row_text = SystemResources._format_cpu_row(snapshot, core_count)
                self._log_row("System CPU", tag, row_text)
        # One threads row per snapshot that has it.
        for tag, snapshot in snapshots_by_tag.items():
            if snapshot is not None and snapshot.get("threads") is not None:
                row_text = SystemResources._format_threads_row(snapshot, tag, user_limit, system_maximum)
                self._log_row("System threads", tag, row_text)

    def _log_row(self, metric: str, tag: str, value: str) -> None:
        """
        Log one aligned metric row so value columns line up.

        :param metric: Metric name, e.g. "System memory"
        :param tag: "before", "peak" or "after"
        :param value: Formatted value
        """
        self.logger.info("  %-14s %-9s %s", metric, f"({tag}):", value)

    @staticmethod
    def _format_memory_row(snapshot: SystemSnapshot, total_gigabytes: float) -> str:
        """
        Format a memory row: used / free / percent.

        :param snapshot: System snapshot; log_section passes only one whose "memory_percent" is not None
        :param total_gigabytes: Total system memory in GB
        :return: e.g. '8192 MB used / 7.5 GB free (50% used)', with 'n/a free' when "available_gigabytes" is None
        """
        memory_percentage: Optional[float] = snapshot.get("memory_percent", 0.0)
        available_gigabytes: Optional[float] = snapshot.get("available_gigabytes", 0.0)
        used_fraction: float = memory_percentage / ResourceMonitor.ONE_HUNDRED_PERCENT
        used_gigabytes: float = used_fraction * total_gigabytes
        used_megabytes: float = used_gigabytes * ResourceMonitor.MEGABYTES_PER_GIGABYTE
        # A stage summary can have the memory percentage without the free memory.
        free_text: str = "n/a"
        if available_gigabytes is not None:
            free_text = f"{available_gigabytes:.1f} GB"
        return f"{used_megabytes:.0f} MB used / {free_text} free ({memory_percentage:.0f}% used)"

    @staticmethod
    def _format_cpu_row(snapshot: SystemSnapshot, core_count: int) -> str:
        """
        Format a CPU row: percent and core-equivalents.

        :param snapshot: System snapshot; log_section passes only one whose "cpu_percent" is not None
        :param core_count: Number of CPU cores
        :return: e.g. '50% (2.00 of 4 cores)'
        """
        cpu_percentage: Optional[float] = snapshot.get("cpu_percent", 0.0)
        cores_in_use: float = ResourceMonitor.cores_in_use(cpu_percentage, core_count)
        return f"{cpu_percentage:.0f}% ({cores_in_use:.2f} of {core_count} cores)"

    @staticmethod
    def _format_threads_row(snapshot: SystemSnapshot, tag: str, user_limit: str, system_maximum: str) -> str:
        """
        Format a threads row; limits only on the before row.

        :param snapshot: System snapshot; log_section passes only one whose "threads" is not None
        :param tag: "before", "peak" or "after"
        :param user_limit: Per-user thread limit from thread_limits
        :param system_maximum: System thread max from thread_limits
        :return: e.g. '1,234 in use', with the limits added on the before row
        """
        thread_count: Optional[float] = snapshot.get("threads", 0)
        threads: int = int(thread_count)
        if tag == "before":
            return f"{threads:,} in use / limit {user_limit} per-user ({system_maximum} max)"
        return f"{threads:,} in use"
