
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
from typing import Dict
from typing import Optional
from unittest import TestCase

from tests.load_tests.monitoring.kernel_memory import KernelMemory


class TestKernelMemory(TestCase):
    """
    Unit tests for KernelMemory: reading /proc and the kernel memory breakdown.
    """

    def test_read_kernel_memory_has_meminfo_and_tcp_values(self) -> None:
        """
        On Linux the values come from /proc/meminfo and /proc/net/sockstat; elsewhere there are none.
        """
        kernel_memory: Optional[Dict[str, float]] = KernelMemory.read_kernel_memory()
        if kernel_memory is None:
            self.skipTest("/proc/meminfo is not available")
        self.assertIn("MemTotal", kernel_memory)
        self.assertIn("TcpMem", kernel_memory)
        memory_total_megabytes: float = kernel_memory.get("MemTotal")
        self.assertGreater(memory_total_megabytes, 0.0)

    def test_kernel_breakdown_of_no_values_is_empty(self) -> None:
        """
        Without kernel values there is nothing to break down.
        """
        none_breakdown: Dict[str, float] = KernelMemory().kernel_breakdown(None, 100.0, log=False)
        empty_breakdown: Dict[str, float] = KernelMemory().kernel_breakdown({}, 100.0, log=False)
        self.assertEqual(none_breakdown, {})
        self.assertEqual(empty_breakdown, {})

    def test_kernel_breakdown_adds_up_the_parts(self) -> None:
        """
        The accounted memory is the server RSS plus the kernel parts; the rest of the used memory is unaccounted.
        """
        after_kernel: Dict[str, float] = {
            "KernelStack": 10.0, "PageTables": 20.0, "Slab": 30.0, "Cached": 40.0, "Buffers": 5.0,
            "TcpMem": 4.0, "MemTotal": 1000.0, "MemFree": 400.0,
        }
        breakdown: Dict[str, float] = KernelMemory().kernel_breakdown(after_kernel, 100.0, log=False)
        expected_breakdown: Dict[str, float] = {
            "server_rss_mb": 100.0,
            "kernel_stacks_mb": 10.0,
            "page_tables_mb": 20.0,
            "slab_mb": 30.0,
            "page_cache_mb": 45.0,
            "tcp_buffers_mb": 4.0,
            "accounted_mb": 209.0,
            "unaccounted_mb": 391.0,
            "system_total_mb": 600.0,
        }
        self.assertEqual(breakdown, expected_breakdown)

    def test_kernel_breakdown_without_rss_counts_zero(self) -> None:
        """
        No server RSS counts as 0 MB, and unaccounted memory is never below 0.
        """
        after_kernel: Dict[str, float] = {"Slab": 50.0, "MemTotal": 100.0, "MemFree": 80.0}
        breakdown: Dict[str, float] = KernelMemory().kernel_breakdown(after_kernel, None, log=False)
        rss_megabytes: float = breakdown.get("server_rss_mb")
        unaccounted_megabytes: float = breakdown.get("unaccounted_mb")
        self.assertEqual(rss_megabytes, 0.0)
        self.assertEqual(unaccounted_megabytes, 0)
