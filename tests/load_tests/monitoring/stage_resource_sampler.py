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
from typing import Optional
from typing import Union

from psutil import AccessDenied
from psutil import NoSuchProcess
from psutil import Process
from psutil import cpu_percent
from psutil import swap_memory
from psutil import virtual_memory

from tests.load_tests.monitoring.progress_log_writer import ProgressLogWriter
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.sensitive_error_logger import SensitiveErrorLogger
from tests.load_tests.reporting.system_resources import SystemResources


class StageResourceSampler:
    """
    Takes the heartbeat's resource readings during a stage and keeps their peaks.

    Reads server and client RSS, server threads and swap, and system memory, CPU and threads with psutil,
    and warns once when system memory, system swap or server swap gets high. Only the heartbeat thread
    calls the sample methods; read the peaks with the get_peak_*() methods after that thread is joined.
    """

    # Warn once when system memory use reaches this fraction.
    OUT_OF_MEMORY_WARNING_THRESHOLD: float = 0.80

    def __init__(self, server_process: Optional[Process], client_process: Optional[Process],
                 progress_log_writer: ProgressLogWriter) -> None:
        """
        Constructor.

        :param server_process: Server process for thread count and RSS readings, or None
        :param client_process: Client process for RSS readings, or None
        :param progress_log_writer: Writes the resource warnings to progress.log
        """
        class_logger: Logger = getLogger(self.__class__.__name__)
        self.logger: SensitiveErrorLogger = SensitiveErrorLogger(class_logger)
        self._server_process: Optional[Process] = server_process
        self._client_process: Optional[Process] = client_process
        self._progress_log_writer: ProgressLogWriter = progress_log_writer
        self._out_of_memory_warned: bool = False
        self._swap_warned: bool = False
        # The stage's peak readings, keyed by the get_peak_*() name without "get_peak_".
        # A key is missing until a reading above zero is taken, so the stage summary leaves the peak out.
        self._peaks: Dict[str, Union[int, float, Dict[str, float]]] = {}
        # Prime the non-blocking system CPU counter so the first real
        # sample reflects usage since the heartbeat started rather
        # than returning 0.0.
        cpu_percent(interval=None)

    def get_peak_server_threads(self) -> Optional[int]:
        """
        Read the stage's highest server thread count.

        :return: The highest server thread count of the stage, or None
        """
        peak_server_threads: Optional[int] = self._peaks.get("server_threads")
        return peak_server_threads

    def get_peak_client_rss_megabytes(self) -> Optional[float]:
        """
        Read the stage's highest client RSS in MB.

        :return: The highest client RSS of the stage in MB, or None
        """
        peak_client_rss_megabytes: Optional[float] = self._peaks.get("client_rss_megabytes")
        return peak_client_rss_megabytes

    def get_peak_server_rss_megabytes(self) -> Optional[float]:
        """
        Read the stage's highest server RSS in MB.

        :return: The highest server RSS of the stage in MB, or None
        """
        peak_server_rss_megabytes: Optional[float] = self._peaks.get("server_rss_megabytes")
        return peak_server_rss_megabytes

    def get_peak_system_memory(self) -> Optional[Dict[str, float]]:
        """
        Read the stage's highest system memory use.

        :return: Dict with "memory_percent" and "available_gigabytes" at the highest system memory use of the stage,
            or None
        """
        peak_system_memory: Optional[Dict[str, float]] = self._peaks.get("system_memory")
        return peak_system_memory

    def get_peak_system_cpu_percent(self) -> Optional[float]:
        """
        Read the stage's highest whole-box CPU use in percent.

        :return: The highest whole-box CPU use of the stage in percent, or None
        """
        peak_system_cpu_percent: Optional[float] = self._peaks.get("system_cpu_percent")
        return peak_system_cpu_percent

    def get_peak_system_threads(self) -> Optional[int]:
        """
        Read the stage's highest system-wide thread count.

        :return: The highest system-wide thread count of the stage, or None
        """
        peak_system_threads: Optional[int] = self._peaks.get("system_threads")
        return peak_system_threads

    @staticmethod
    def is_new_peak(sample: float, peak_so_far: Optional[float]) -> bool:
        """
        Tell whether a reading beats the peak so far. A reading of 0 or less is never a peak.

        :param sample: The new reading
        :param peak_so_far: The peak so far, or None when there is none yet
        :return: True when sample is above zero and above peak_so_far
        """
        floor: float = 0.0
        if peak_so_far is not None:
            floor = peak_so_far
        return sample > floor

    def sample_client_rss(self) -> None:
        """
        Sample client RSS and keep it when it is a new peak.
        """
        if self._client_process is None:
            return
        try:
            # psutil returns its private pmem named tuple, which has no public type to name.
            memory_info: Any = self._client_process.memory_info()
            rss_megabytes: float = memory_info.rss / ResourceMonitor.ONE_MEGABYTE
            peak_client_rss_megabytes: Optional[float] = self._peaks.get("client_rss_megabytes")
            if StageResourceSampler.is_new_peak(rss_megabytes, peak_client_rss_megabytes):
                self._peaks["client_rss_megabytes"] = rss_megabytes
        except (NoSuchProcess, AccessDenied) as error:
            self.logger.debug("Heartbeat client RSS unavailable: %s", error)

    def check_server_alive(self) -> bool:
        """
        Tell whether the server process is still running.

        :return: True if the server process is still running
        """
        if self._server_process is None:
            return True
        try:
            return self._server_process.is_running()
        except (NoSuchProcess, AccessDenied):
            return False

    def sample_server_metrics(self) -> Dict[str, str]:
        """
        Sample server thread count and RSS, keeping each when it is a new peak.

        :return: Dict with "thread_info" and "server_rss_info", the parts of the progress line
        """
        thread_info: str = ""
        server_rss_info: str = ""
        if self._server_process is None:
            return StageResourceSampler._server_metrics(thread_info, server_rss_info)
        try:
            server_thread_count: int = self._server_process.num_threads()
            peak_server_threads: Optional[int] = self._peaks.get("server_threads")
            if StageResourceSampler.is_new_peak(server_thread_count, peak_server_threads):
                self._peaks["server_threads"] = server_thread_count
                thread_info = f"  threads: {server_thread_count} (peak)"
            else:
                thread_info = f"  threads: {server_thread_count}"
        except (NoSuchProcess, AccessDenied) as error:
            self.logger.debug("Heartbeat thread count unavailable: %s", error)
        server_memory: Dict[str, Optional[float]] = self._sample_server_memory()
        rss_megabytes: Optional[float] = server_memory.get("rss_megabytes")
        swap_megabytes: Optional[float] = server_memory.get("swap_megabytes")
        if rss_megabytes is not None:
            swap_info: str = ""
            if swap_megabytes > 0:
                swap_text: str = Formatters.format_rss(swap_megabytes)
                swap_info = f" swap: {swap_text}"
            rss_text: str = Formatters.format_rss(rss_megabytes)
            server_rss_info = f"  RSS: {rss_text}{swap_info}"
            peak_server_rss_megabytes: Optional[float] = self._peaks.get("server_rss_megabytes")
            if StageResourceSampler.is_new_peak(rss_megabytes, peak_server_rss_megabytes):
                self._peaks["server_rss_megabytes"] = rss_megabytes
            self._check_memory_warnings(swap_megabytes)
        return StageResourceSampler._server_metrics(thread_info, server_rss_info)

    def system_memory_info(self) -> str:
        """
        Read the system memory for the progress line, recording it as the peak when it is a new peak.

        :return: The system memory part of the progress line
        """
        system_memory: Dict[str, Any] = StageResourceSampler._format_system_memory()
        system_memory_info: str = system_memory.get("text")
        current_memory_percent: float = system_memory.get("memory_percent")
        current_available_gigabytes: float = system_memory.get("available_gigabytes")
        self._sample_system_memory(current_memory_percent, current_available_gigabytes)
        return system_memory_info

    def format_system_cpu(self) -> str:
        """
        Format whole-box CPU utilization with peak-so-far, recording the peak.

        Uses non-blocking ``cpu_percent`` (usage since the previous
        sample) and tracks the peak across the run.  0-100% across
        all cores.

        :return: The CPU part of the progress line
        """
        current_cpu_percent: float = cpu_percent(interval=None)
        # Unlike the other peaks, a 0% first reading is kept, so every tick reports a CPU peak.
        peak_cpu_percent: float = self._peaks.get("system_cpu_percent", current_cpu_percent)
        peak_cpu_percent = max(peak_cpu_percent, current_cpu_percent)
        self._peaks["system_cpu_percent"] = peak_cpu_percent
        cpu_text: str = f"  syscpu: {current_cpu_percent:.0f}% (peak {peak_cpu_percent:.0f}%)"
        return cpu_text

    def sample_system_threads(self) -> None:
        """
        Keep the system thread count when it is a new peak.
        """
        current_system_threads: int = SystemResources.total_threads()
        peak_system_threads: Optional[int] = self._peaks.get("system_threads")
        if StageResourceSampler.is_new_peak(current_system_threads, peak_system_threads):
            self._peaks["system_threads"] = current_system_threads

    @staticmethod
    def _server_metrics(thread_info: str, server_rss_info: str) -> Dict[str, str]:
        """
        Put the server parts of the progress line in the dict sample_server_metrics() returns.

        :param thread_info: Thread count text, or ""
        :param server_rss_info: RSS and swap text, or ""
        :return: Dict with "thread_info" and "server_rss_info"
        """
        server_metrics: Dict[str, str] = {
            "thread_info": thread_info,
            "server_rss_info": server_rss_info,
        }
        return server_metrics

    def _sample_server_memory(self) -> Dict[str, Optional[float]]:
        """
        Sample server RSS and swap in MB.

        :return: Dict with "rss_megabytes" and "swap_megabytes", each None if unavailable
        """
        server_memory: Dict[str, Optional[float]] = {
            "rss_megabytes": None,
            "swap_megabytes": None,
        }
        if self._server_process is None:
            return server_memory
        try:
            # psutil returns its private pfullmem named tuple, which has no public type to name.
            memory_info: Any = self._server_process.memory_full_info()
            server_memory["rss_megabytes"] = memory_info.rss / ResourceMonitor.ONE_MEGABYTE
            server_memory["swap_megabytes"] = memory_info.swap / ResourceMonitor.ONE_MEGABYTE
        except (NoSuchProcess, AccessDenied) as error:
            self.logger.debug("Heartbeat server memory unavailable: %s", error)
            server_memory["rss_megabytes"] = None
            server_memory["swap_megabytes"] = None
        return server_memory

    def _check_memory_warnings(self, swap_megabytes: float) -> None:
        """
        Warn if system memory or swap exceeds thresholds.

        :param swap_megabytes: Server swap in MB
        """
        self._check_system_memory_warning()
        if not self._swap_warned and swap_megabytes > 0:
            self._swap_warned = True
            swap_text: str = Formatters.format_rss(swap_megabytes)
            warning: str = f"  WARNING: Server has {swap_text} swapped to disk — severe performance impact"
            self.logger.warning("%s", warning)
            self._progress_log_writer.write_to_file(warning)

    def _check_system_memory_warning(self) -> None:
        """
        Warn when total system memory usage exceeds threshold.
        """
        if self._out_of_memory_warned:
            return
        # psutil returns its private svmem named tuple, which has no public type to name.
        virtual_memory_stats: Any = virtual_memory()
        used_fraction: float = virtual_memory_stats.percent / 100.0
        if used_fraction >= StageResourceSampler.OUT_OF_MEMORY_WARNING_THRESHOLD:
            self._out_of_memory_warned = True
            total_gigabytes: float = virtual_memory_stats.total / ResourceMonitor.ONE_GIGABYTE
            available_gigabytes: float = virtual_memory_stats.available / ResourceMonitor.ONE_GIGABYTE
            warning: str = (f"  WARNING: System memory at {virtual_memory_stats.percent:.0f}%"
                            f" ({available_gigabytes:.1f} GB free / {total_gigabytes:.1f} GB total) — risk of OOM kill")
            self.logger.warning("%s", warning)
            self._progress_log_writer.write_to_file(warning)
            # psutil returns its private sswap named tuple, which has no public type to name.
            swap_memory_stats: Any = swap_memory()
            if swap_memory_stats.total > 0 and swap_memory_stats.used > 0:
                swap_used_gigabytes: float = swap_memory_stats.used / ResourceMonitor.ONE_GIGABYTE
                swap_warning: str = (f"  WARNING: System swap in use: {swap_used_gigabytes:.1f} GB"
                                     " — severe performance impact")
                self.logger.warning("%s", swap_warning)
                self._progress_log_writer.write_to_file(swap_warning)

    @staticmethod
    def _format_system_memory() -> Dict[str, Any]:
        """
        Format total system memory usage for the progress line.

        :return: Dict with "text" (the progress line part), "memory_percent" and "available_gigabytes"
        """
        # psutil returns its private svmem named tuple, which has no public type to name.
        virtual_memory_stats: Any = virtual_memory()
        available_gigabytes: float = virtual_memory_stats.available / ResourceMonitor.ONE_GIGABYTE
        line: str = ResourceMonitor.system_memory_text(virtual_memory_stats)
        system_memory: Dict[str, Any] = {
            "text": line,
            "memory_percent": virtual_memory_stats.percent,
            "available_gigabytes": available_gigabytes,
        }
        return system_memory

    def _sample_system_memory(self, memory_percent: float, available_gigabytes: float) -> None:
        """
        Keep the system memory reading when it is a new peak.

        :param memory_percent: Current system memory use in percent
        :param available_gigabytes: Current available system memory in GB
        """
        peak_memory_percent: Optional[float] = None
        peak_system_memory: Optional[Dict[str, float]] = self._peaks.get("system_memory")
        if peak_system_memory is not None:
            peak_memory_percent = peak_system_memory.get("memory_percent")
        if StageResourceSampler.is_new_peak(memory_percent, peak_memory_percent):
            new_peak_system_memory: Dict[str, float] = {
                "memory_percent": memory_percent,
                "available_gigabytes": available_gigabytes,
            }
            self._peaks["system_memory"] = new_peak_system_memory
