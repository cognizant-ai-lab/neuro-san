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

import psutil


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

    @staticmethod
    def find_process(keyword: str) -> Optional[psutil.Process]:
        """
        Find a running process whose command line contains the given keyword.

        :param keyword: Text to look for in each process command line
        :return: The first matching process, or None
        """
        process: psutil.Process
        # Return the first process whose command line has the keyword.
        for process in psutil.process_iter(["pid", "cmdline"]):
            try:
                command_line: str = " ".join(process.info.get("cmdline") or [])
                if keyword in command_line:
                    return psutil.Process(process.info.get("pid"))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def find_process_by_port(port: int) -> Optional[psutil.Process]:
        """
        Find a process listening on the given port.

        :param port: TCP port the process listens on
        :return: The first process listening on the port, or None
        """
        process: psutil.Process
        # Look for a process with a listening connection on the port.
        for process in psutil.process_iter(["pid"]):
            try:
                connection: Any
                # Check each connection of the process for a listen on the port.
                for connection in process.net_connections():
                    if connection.status == "LISTEN" and connection.laddr.port == port:
                        return psutil.Process(process.info.get("pid"))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def snapshot(process: Optional[psutil.Process]) -> Optional[Dict[str, Any]]:
        """
        Capture a point-in-time resource snapshot of a process.

        :param process: Process to measure, or None
        :return: A dictionary with "rss" (megabytes), "fds", "threads", "connections", "children", "cpu" (percent)
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
            children: List[psutil.Process] = process.children()
            child_count: int = len(children)
            cpu_percentage: float = process.cpu_percent(interval=0.1)
            cpu_seconds: float = cpu_times.user + cpu_times.system
            process_snapshot: Dict[str, Any] = {
                "rss": rss_megabytes,
                "fds": file_descriptor_count,
                "threads": thread_count,
                "connections": connection_count,
                "children": child_count,
                "cpu": cpu_percentage,
                "cpu_seconds": cpu_seconds,
            }
            return process_snapshot
        except (psutil.NoSuchProcess, psutil.AccessDenied):
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
        logger.info(
            "  %s: RSS=%.1f MB, FDs=%s, Threads=%s, Conns=%s, CPU=%.1f%%, Children=%s",
            label, resource_snapshot.get("rss"), resource_snapshot.get("fds"), resource_snapshot.get("threads"),
            resource_snapshot.get("connections"), resource_snapshot.get("cpu"), resource_snapshot.get("children"),
        )
