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
from os.path import isfile
from typing import Dict
from typing import List
from typing import Optional


class KernelMemory:
    """
    Reads the kernel memory values from /proc and works out how much memory the kernel holds outside the server.
    """

    KILOBYTES_PER_MEGABYTE: float = 1024.0
    TCP_PAGE_KILOBYTES: int = 4
    # Linux files with the kernel memory counters and the TCP buffer pages.
    MEMINFO_FILE: str = "/proc/meminfo"
    SOCKSTAT_FILE: str = "/proc/net/sockstat"
    # 30 box-drawing "─" characters: the line above the kernel memory totals.
    KERNEL_TOTAL_LINE: str = "──────────────────────────────"

    def __init__(self) -> None:
        """
        Set up the logger.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    @staticmethod
    def read_kernel_memory() -> Optional[Dict[str, float]]:
        """
        Read kernel memory breakdown from /proc/meminfo.

        :return: A dict of every /proc/meminfo value in MB plus "TcpMem" (TCP buffers in MB, 0.0 when
                 /proc/net/sockstat can't be read), or None when /proc/meminfo is missing or can't be read
        """
        if not isfile(KernelMemory.MEMINFO_FILE):
            return None
        meminfo_megabytes: Dict[str, float] = {}
        parts: List[str] = []
        meminfo_key: str = ""
        value_kilobytes: int = 0
        try:
            with open(KernelMemory.MEMINFO_FILE, "r", encoding="utf-8") as meminfo_file:
                line: str
                # Read each meminfo value in megabytes.
                for line in meminfo_file:
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    meminfo_key = parts[0].rstrip(":")
                    value_kilobytes = int(parts[1])
                    meminfo_megabytes[meminfo_key] = value_kilobytes / KernelMemory.KILOBYTES_PER_MEGABYTE
        except (OSError, ValueError):
            return None

        tcp_memory_megabytes: float = 0.0
        mem_index: int = 0
        tcp_pages: int = 0
        tcp_kilobytes: int = 0
        try:
            with open(KernelMemory.SOCKSTAT_FILE, "r", encoding="utf-8") as sockstat_file:
                # Read the TCP memory pages from the TCP: line.
                for line in sockstat_file:
                    if line.startswith("TCP:"):
                        parts = line.split()
                        mem_index = parts.index("mem")
                        tcp_pages = int(parts[mem_index + 1])
                        tcp_kilobytes = tcp_pages * KernelMemory.TCP_PAGE_KILOBYTES
                        tcp_memory_megabytes = tcp_kilobytes / KernelMemory.KILOBYTES_PER_MEGABYTE
                        break
        except (OSError, ValueError, IndexError):
            pass
        meminfo_megabytes["TcpMem"] = tcp_memory_megabytes
        return meminfo_megabytes

    def kernel_breakdown(self, after_kernel: Optional[Dict[str, float]], server_rss_peak_megabytes: Optional[float],
                         log: bool = True) -> Dict[str, float]:
        """
        Compute the kernel memory breakdown.

        When ``log`` is False the values are still returned for JSON
        export but nothing is printed to the console.

        :param after_kernel: Kernel memory values in MB from read_kernel_memory(), or None
        :param server_rss_peak_megabytes: Peak server RSS in MB (the caller passes the after-round RSS when there
                                          is no peak)
        :param log: When True, the breakdown is also logged
        :return: A dict with the following keys, all in MB, or {} when after_kernel is empty:
                 "server_rss_mb"     Server RSS
                 "kernel_stacks_mb"  Kernel stacks
                 "page_tables_mb"    Page tables
                 "slab_mb"           Kernel slab
                 "page_cache_mb"     Page cache
                 "tcp_buffers_mb"    TCP buffers
                 "accounted_mb"      Sum of the parts above
                 "unaccounted_mb"    Used memory not in the parts above
                 "system_total_mb"   Total system memory
        """
        if not after_kernel:
            return {}

        rss_megabytes: float = 0.0
        if server_rss_peak_megabytes:
            rss_megabytes = server_rss_peak_megabytes
        kernel_stacks_megabytes: float = after_kernel.get("KernelStack", 0)
        page_tables_megabytes: float = after_kernel.get("PageTables", 0)
        slab_megabytes: float = after_kernel.get("Slab", 0)
        page_cache_megabytes: float = after_kernel.get("Cached", 0)
        page_cache_megabytes += after_kernel.get("Buffers", 0)
        tcp_buffers_megabytes: float = after_kernel.get("TcpMem", 0)
        system_used_megabytes: float = KernelMemory._system_used_megabytes(after_kernel)

        accounted_megabytes: float = rss_megabytes + kernel_stacks_megabytes + page_tables_megabytes + slab_megabytes
        accounted_megabytes += page_cache_megabytes
        accounted_megabytes += tcp_buffers_megabytes
        unaccounted_megabytes: float = max(0, system_used_megabytes - accounted_megabytes)

        breakdown: Dict[str, float] = {
            "server_rss_mb": rss_megabytes,
            "kernel_stacks_mb": kernel_stacks_megabytes,
            "page_tables_mb": page_tables_megabytes,
            "slab_mb": slab_megabytes,
            "page_cache_mb": page_cache_megabytes,
            "tcp_buffers_mb": tcp_buffers_megabytes,
            "accounted_mb": accounted_megabytes,
            "unaccounted_mb": unaccounted_megabytes,
            "system_total_mb": system_used_megabytes,
        }
        if log:
            self._log_breakdown(breakdown)
        return breakdown

    @staticmethod
    def _system_used_megabytes(after_kernel: Dict[str, float]) -> float:
        """
        Work out the system memory in use, page cache included.

        :param after_kernel: Kernel memory values in MB from read_kernel_memory()
        :return: MemTotal minus MemFree, in MB
        """
        memory_total_megabytes: float = after_kernel.get("MemTotal", 0)
        memory_free_megabytes: float = after_kernel.get("MemFree", 0)
        system_used_megabytes: float = memory_total_megabytes - memory_free_megabytes
        return system_used_megabytes

    def _log_breakdown(self, breakdown: Dict[str, float]) -> None:
        """
        Log the kernel memory breakdown, one line per part.

        :param breakdown: The dict kernel_breakdown() returns
        """
        server_rss_megabytes: float = breakdown.get("server_rss_mb")
        kernel_stacks_megabytes: float = breakdown.get("kernel_stacks_mb")
        page_tables_megabytes: float = breakdown.get("page_tables_mb")
        slab_megabytes: float = breakdown.get("slab_mb")
        page_cache_megabytes: float = breakdown.get("page_cache_mb")
        tcp_buffers_megabytes: float = breakdown.get("tcp_buffers_mb")
        accounted_megabytes: float = breakdown.get("accounted_mb")
        unaccounted_megabytes: float = breakdown.get("unaccounted_mb")
        system_total_megabytes: float = breakdown.get("system_total_mb")
        self.logger.info("\n  Kernel memory breakdown:")
        self.logger.info("    Server RSS:       %.0f MB", server_rss_megabytes)
        self.logger.info("    Kernel stacks:    %.0f MB", kernel_stacks_megabytes)
        self.logger.info("    Page tables:      %.0f MB", page_tables_megabytes)
        self.logger.info("    Slab cache:       %.0f MB", slab_megabytes)
        self.logger.info("    Page cache:       %.0f MB", page_cache_megabytes)
        self.logger.info("    TCP buffers:      %.0f MB", tcp_buffers_megabytes)
        self.logger.info("    %s", KernelMemory.KERNEL_TOTAL_LINE)
        self.logger.info("    Accounted:        %.0f MB", accounted_megabytes)
        self.logger.info("    Unaccounted:      %.0f MB", unaccounted_megabytes)
        self.logger.info("    System total:     %.0f MB (used + cache)", system_total_megabytes)
