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

import logging
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from psutil import AccessDenied
from psutil import NoSuchProcess
from psutil import Process
from psutil import process_iter
from psutil import virtual_memory


logger: logging.Logger = logging.getLogger(__name__)


class ResourceMonitor:
    """
    Captures and logs psutil-based process resource snapshots.

    Interim implementation. May be replaced by neuro-san built-in
    monitoring and telemetry when those features become available.
    """

    # Bytes in a megabyte and in a gigabyte, to convert memory readings
    ONE_MEGABYTE: int = 1024 ** 2
    ONE_GIGABYTE: int = 1024 ** 3
    # Megabytes in a gigabyte, to show megabyte values in gigabytes
    MEGABYTES_PER_GIGABYTE: int = 1024
    # A percentage that stands for one whole (one core, all memory)
    ONE_HUNDRED_PERCENT: float = 100.0

    @staticmethod
    def cores_in_use(cpu_percentage: float, core_count: int) -> float:
        """
        Convert a whole-system CPU percentage into the number of cores it keeps busy.

        :param cpu_percentage: CPU use in percent of all cores, e.g. 50.0
        :param core_count: Number of CPU cores
        :return: Cores in use, e.g. 2.0 for 50.0 percent of 4 cores
        """
        used_fraction: float = cpu_percentage / ResourceMonitor.ONE_HUNDRED_PERCENT
        cores: float = used_fraction * core_count
        return cores

    @staticmethod
    def find_process(keyword: str) -> Optional[Process]:
        """
        Find a running process whose command line contains the given keyword.

        :param keyword: Text to look for in each process command line
        :return: The first matching process, or None
        """
        process: Process
        # Return the first process whose command line has the keyword.
        for process in process_iter(["pid", "cmdline"]):
            try:
                command_line: str = " ".join(process.info.get("cmdline") or [])
                if keyword in command_line:
                    return Process(process.info.get("pid"))
            except (NoSuchProcess, AccessDenied):
                continue
        return None

    @staticmethod
    def find_process_by_port(port: int) -> Optional[Process]:
        """
        Find a process listening on the given port.

        :param port: TCP port the process listens on
        :return: The first process listening on the port, or None
        """
        process: Process
        # Look for a process with a listening connection on the port.
        for process in process_iter(["pid"]):
            try:
                connection: Any
                # Check each connection of the process for a listen on the port.
                for connection in process.net_connections():
                    if connection.status == "LISTEN" and connection.laddr.port == port:
                        return Process(process.info.get("pid"))
            except (NoSuchProcess, AccessDenied):
                continue
        return None

    @staticmethod
    def snapshot(process: Optional[Process]) -> Optional[Dict[str, Any]]:
        """
        Capture a point-in-time resource snapshot of a process.

        :param process: Process to measure, or None
        :return: A dictionary with "rss_megabytes", "fds", "threads", "connections", "children", "cpu_percent"
            and "cpu_seconds"; None if the process cannot be read
        """
        if process is None:
            return None
        try:
            memory_info: Any = process.memory_info()
            file_descriptor_count: int = 0
            try:
                file_descriptor_count = process.num_fds()
            except AttributeError:
                file_descriptor_count = process.num_handles()
            cpu_times: Any = process.cpu_times()
            rss_megabytes: float = memory_info.rss / ResourceMonitor.ONE_MEGABYTE
            thread_count: int = process.num_threads()
            # net_connections() returns psutil's private pconn named tuples, which have no public type to name.
            connections: List[Any] = process.net_connections()
            connection_count: int = len(connections)
            children: List[Process] = process.children()
            child_count: int = len(children)
            cpu_percentage: float = process.cpu_percent(interval=0.1)
            cpu_seconds: float = cpu_times.user + cpu_times.system
            process_snapshot: Dict[str, Any] = {
                "rss_megabytes": rss_megabytes,
                "fds": file_descriptor_count,
                "threads": thread_count,
                "connections": connection_count,
                "children": child_count,
                "cpu_percent": cpu_percentage,
                "cpu_seconds": cpu_seconds,
            }
            return process_snapshot
        except (NoSuchProcess, AccessDenied):
            return None

    @staticmethod
    def log_snapshot(label: str, resource_snapshot: Optional[Dict[str, Any]]) -> None:
        """
        Log a single resource snapshot.

        :param label: Label shown before the values
        :param resource_snapshot: Snapshot from snapshot(), or None
        """
        if resource_snapshot is None:
            logger.info("  %s: process not found", label)
            return
        rss_megabytes: float = resource_snapshot.get("rss_megabytes")
        file_descriptor_count: int = resource_snapshot.get("fds")
        thread_count: int = resource_snapshot.get("threads")
        connection_count: int = resource_snapshot.get("connections")
        cpu_percent: float = resource_snapshot.get("cpu_percent")
        child_count: int = resource_snapshot.get("children")
        logger.info("  %s: RSS=%.1f MB, FDs=%s, Threads=%s, Conns=%s, CPU=%.1f%%, Children=%s", label,
                    rss_megabytes, file_descriptor_count, thread_count, connection_count, cpu_percent, child_count)

    @staticmethod
    def log_system_memory(label: str) -> None:
        """
        Log the system memory: percent used, then used, free and total.

        :param label: Label after "System", e.g. "BEFORE"
        """
        # psutil.virtual_memory() returns psutil's private svmem named tuple, which has no public type to name.
        virtual_memory_stats: Any = virtual_memory()
        used_bytes: int = virtual_memory_stats.total - virtual_memory_stats.available
        used_megabytes: float = used_bytes / ResourceMonitor.ONE_MEGABYTE
        available_gigabytes: float = virtual_memory_stats.available / ResourceMonitor.ONE_GIGABYTE
        total_gigabytes: float = virtual_memory_stats.total / ResourceMonitor.ONE_GIGABYTE
        logger.info("  System %s: %.0f%% used (%.0fM used / %.1fG free / %.1fG total)",
                    label, virtual_memory_stats.percent, used_megabytes, available_gigabytes, total_gigabytes)
