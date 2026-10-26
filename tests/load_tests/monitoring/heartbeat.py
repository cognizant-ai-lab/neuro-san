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

# Whole re module: "from re import compile" would hide the builtin compile().
import re
# Whole sys module: sys.stdout is looked up on each write, so a swapped stdout is used.
import sys
from concurrent.futures import CancelledError
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from logging import Logger
from logging import getLogger
from os.path import join
from threading import Event
from threading import Lock
from time import localtime
from time import perf_counter
from time import strftime
from time import struct_time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from psutil import AccessDenied
from psutil import NoSuchProcess
from psutil import Process
from psutil import cpu_percent
from psutil import swap_memory
from psutil import virtual_memory

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.system_resources import SystemResources

CONSOLE_INTERVAL_TICKS: int = 1
OUT_OF_MEMORY_WARNING_THRESHOLD: float = 0.80


class Heartbeat:  # pylint: disable=too-many-instance-attributes
    """
    Logs periodic progress while requests are in-flight.

    Holds the server process handle so the heartbeat thread can
    read thread counts without the caller passing it each time.

    Also keeps the stage's peak readings. The heartbeat thread writes
    them; read them with the get_peak_*() methods after join().

    Interim implementation. May be replaced by neuro-san built-in
    monitoring and telemetry when those features become available.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
            self, server_process: Optional[Process],
            client_process: Optional[Process] = None,
            output_dir: Optional[str] = None,
            log_monitor: Optional[ServerLogMonitor] = None,
            log_start_position: Optional[int] = None,
            primary_start_pattern: Optional[str] = None,
    ) -> None:
        """
        Constructor.

        :param server_process: Server process for thread count and RSS readings, or None
        :param client_process: Client process for RSS readings, or None
        :param output_dir: Directory for progress.log, or None for console only
        :param log_monitor: Server log reader for server-side request timing, or None
        :param log_start_position: Server log offset where the stage started, or None
        :param primary_start_pattern: Regex for the log line of a primary agent request starting, or None
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self._server_process: Optional[Process] = server_process
        self._client_process: Optional[Process] = client_process
        self._output_dir: Optional[str] = output_dir
        self._total_system_ram_bytes: int = virtual_memory().total
        self._out_of_memory_warned: bool = False
        self._swap_warned: bool = False
        self._console_started: bool = False
        # None until a reading above zero is taken, so the stage summary leaves the peak out.
        self._peak_server_threads: Optional[int] = None
        self._peak_client_rss_megabytes: Optional[float] = None
        self._peak_server_rss_megabytes: Optional[float] = None
        self._peak_system_memory: Optional[Dict[str, float]] = None
        self._peak_system_cpu_percent: Optional[float] = None
        self._peak_system_threads: Optional[int] = None
        # Request worker threads add to this while the heartbeat thread reads it.
        self._failed_request_count: int = 0
        self._failed_request_lock: Lock = Lock()
        # progress_heartbeat() notes when the done count last changed, to report stalled requests.
        self._last_done_count: int = 0
        self._last_change_seconds: float = 0.0
        # Prime the non-blocking system CPU counter so the first real
        # sample reflects usage since the heartbeat started rather
        # than returning 0.0.
        cpu_percent(interval=None)
        # Optional server-log source for per-request server-side
        # timing.  When set, the heartbeat parses primary
        # streaming_chat Start/Finish pairs to report cumulative
        # server-side min/avg/max durations.
        self._log_monitor: Optional[ServerLogMonitor] = log_monitor
        self._log_start_position: Optional[int] = log_start_position
        self._primary_start_regex: Optional[re.Pattern] = None
        if primary_start_pattern:
            self._primary_start_regex = re.compile(primary_start_pattern)

    def get_peak_server_threads(self) -> Optional[int]:
        """
        :return: The highest server thread count of the stage, or None
        """
        return self._peak_server_threads

    def get_peak_client_rss_megabytes(self) -> Optional[float]:
        """
        :return: The highest client RSS of the stage in MB, or None
        """
        return self._peak_client_rss_megabytes

    def get_peak_server_rss_megabytes(self) -> Optional[float]:
        """
        :return: The highest server RSS of the stage in MB, or None
        """
        return self._peak_server_rss_megabytes

    def get_peak_system_memory(self) -> Optional[Dict[str, float]]:
        """
        :return: {"memory_percent", "available_gigabytes"} at the highest system memory use of the stage, or None
        """
        return self._peak_system_memory

    def get_peak_system_cpu_percent(self) -> Optional[float]:
        """
        :return: The highest whole-box CPU use of the stage in percent, or None
        """
        return self._peak_system_cpu_percent

    def get_peak_system_threads(self) -> Optional[int]:
        """
        :return: The highest system-wide thread count of the stage, or None
        """
        return self._peak_system_threads

    def count_failed_request(self) -> None:
        """
        Add one failed request to the count on the progress line. Called from the request worker threads.
        """
        with self._failed_request_lock:
            self._failed_request_count += 1

    def get_failed_request_count(self) -> int:
        """
        :return: Number of failed requests counted so far
        """
        with self._failed_request_lock:
            return self._failed_request_count

    def progress_heartbeat(self, futures: List[Future], total: int, start_seconds: float,
                           events: Dict[str, Event]) -> None:
        """
        Log periodic progress while requests are in-flight.

        Signals ready_event after the initial RSS sample so the
        caller can wait for the heartbeat to be ready before
        firing requests.  Waits for fires_done_event before
        printing progress so ticks do not overlap receipt dots.

        :param futures: Futures of the requests fired in this stage
        :param total: Number of requests in this stage
        :param start_seconds: perf_counter() value taken when the stage began
        :param events: The stage's events: "stop_event" (set by the caller to stop the heartbeat),
            "ready_event" (set once the initial RSS sample is taken), "fires_done_event" (set by the caller
            once every request is fired) and "server_dead_event" (set when the server process is found dead)
        """
        stop_event: Event = events.get("stop_event")
        ready_event: Event = events.get("ready_event")
        fires_done_event: Event = events.get("fires_done_event")
        server_dead_event: Event = events.get("server_dead_event")
        self._last_done_count = 0
        self._last_change_seconds = start_seconds
        tick_count: int = 0
        self._sample_client_rss()
        ready_event.set()
        fires_done_event.wait()
        self._write_to_file("", end="")
        stopped: bool = False
        line: str = ""
        while True:
            stopped = stop_event.wait(timeout=LoadTestConstants.HEARTBEAT_INTERVAL_SECONDS)
            if not stopped and not self._check_server_alive():
                self.logger.error("\n  ABORT: Server process is no longer running. Possible OOM kill.")
                server_dead_event.set()
                break
            self._sample_client_rss()
            tick_count += 1
            line = self._progress_line(futures, total, start_seconds)
            self._write_to_file(line)
            self._write_to_console(tick_count, line, force=stopped)
            if stopped:
                break

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

    @staticmethod
    def format_elapsed(seconds: int) -> str:
        """
        Format seconds with minutes when >= 60.

        :param seconds: Elapsed seconds
        :return: The formatted duration
        """
        if seconds >= 60:
            # Whole minutes, e.g. 150 seconds -> 2 minutes
            minutes: int = int(seconds / 60)
            return f"{seconds}s ({minutes}m)"
        return f"{seconds}s"

    @staticmethod
    def format_duration_stats(durations: List[float]) -> str:
        """
        Format cumulative min/avg/max over durations.

        :param durations: Request durations in seconds
        :return: The min/avg/max text, or "n/a" when there are no durations yet
        """
        if not durations:
            return "n/a"
        shortest_seconds: float = min(durations)
        longest_seconds: float = max(durations)
        total_seconds: float = sum(durations)
        duration_count: int = len(durations)
        min_seconds: int = int(shortest_seconds)
        max_seconds: int = int(longest_seconds)
        average_float: float = total_seconds / duration_count
        average_seconds: int = int(average_float)
        min_text: str = Heartbeat.format_elapsed(min_seconds)
        average_text: str = Heartbeat.format_elapsed(average_seconds)
        max_text: str = Heartbeat.format_elapsed(max_seconds)
        duration_stats_text: str = f"{min_text} min / {average_text} avg / {max_text} max"
        return duration_stats_text

    def _progress_line(self, futures: List[Future], total: int, start_seconds: float) -> str:
        """
        Take one tick's readings and build its progress line.

        Also keeps the new peaks and logs the memory warnings.

        :param futures: Futures of the requests fired in this stage
        :param total: Number of requests in this stage
        :param start_seconds: perf_counter() value taken when the stage began
        :return: The progress line
        """
        readings: Dict[str, str] = self._progress_readings(futures, total, start_seconds)
        progress_head: str = readings.get("progress_head")
        thread_info: str = readings.get("thread_info")
        server_rss_info: str = readings.get("server_rss_info")
        system_memory_info: str = self._system_memory_info()
        duration_info: str = self._duration_info(futures)
        system_cpu_info: str = self._format_system_cpu()
        self._sample_system_threads()
        line: str = (f"  [progress] {progress_head}  {duration_info.strip()}{thread_info}{server_rss_info}"
                     f"{system_memory_info}{system_cpu_info}")
        return line

    def _progress_readings(self, futures: List[Future], total: int, start_seconds: float) -> Dict[str, str]:
        """
        Take the counts, times and server readings for the progress line.

        The server is sampled after the stall check and before the failed count is read.

        :param futures: Futures of the requests fired in this stage
        :param total: Number of requests in this stage
        :param start_seconds: perf_counter() value taken when the stage began
        :return: The dict from _sample_server_metrics(), plus "progress_head":
            "<done> of <total> completed (<percent>%) -- <elapsed> elapsed [<clock time>]",
            with the failed count inside the brackets and the stalled requests at the end when there are any
        """
        done_count: int = Heartbeat._count_done(futures)
        elapsed_seconds: int = int(perf_counter() - start_seconds)
        local_time: struct_time = localtime()
        timestamp: str = strftime("%H:%M:%S", local_time)
        percent_done: int = Heartbeat._percent(done_count, total)
        stall_info: str = self._stall_info(done_count, total)
        readings: Dict[str, str] = self._sample_server_metrics()
        fail_info: str = self._fail_info(done_count)
        elapsed_text: str = Heartbeat.format_elapsed(elapsed_seconds)
        progress_head: str = (f"{done_count} of {total} completed ({percent_done}%{fail_info}) --"
                              f" {elapsed_text} elapsed [{timestamp}]{stall_info}")
        readings["progress_head"] = progress_head
        return readings

    def _stall_info(self, done_count: int, total: int) -> str:
        """
        Report the requests stalled since the done count last changed, and note when it changes.

        :param done_count: Requests finished so far
        :param total: Number of requests in this stage
        :return: The stalled part of the progress line, or ""
        """
        stall_info: str = ""
        in_flight: int = total - done_count
        if done_count == self._last_done_count and done_count < total:
            stall_seconds: int = int(perf_counter() - self._last_change_seconds)
            stall_text: str = Heartbeat.format_elapsed(stall_seconds)
            stall_info = f"  !! {in_flight} request(s) stalled for {stall_text}"
        if done_count > self._last_done_count:
            self._last_change_seconds = perf_counter()
            self._last_done_count = done_count
        return stall_info

    def _fail_info(self, done_count: int) -> str:
        """
        Format the failed requests for the progress line.

        :param done_count: Requests finished so far
        :return: ", <failed> failed <percent>%", or "" when no request failed
        """
        failed_count: int = self.get_failed_request_count()
        fail_info: str = ""
        if failed_count > 0:
            failed_percent: int = Heartbeat._percent(failed_count, done_count)
            fail_info = f", {failed_count} failed {failed_percent}%"
        return fail_info

    def _system_memory_info(self) -> str:
        """
        Read the system memory for the progress line, keeping it when it is a new peak.

        :return: The system memory part of the progress line
        """
        system_memory: Dict[str, Any] = Heartbeat._format_system_memory()
        system_memory_info: str = system_memory.get("text")
        current_memory_percent: float = system_memory.get("memory_percent")
        current_available_gigabytes: float = system_memory.get("available_gigabytes")
        self._sample_system_memory(current_memory_percent, current_available_gigabytes)
        return system_memory_info

    def _duration_info(self, futures: List[Future]) -> str:
        """
        Format the client and server request durations for the progress line.

        :param futures: Futures of the requests fired in this stage
        :return: The dur/client part, and the dur/server part when the server log is read
        """
        client_durations: List[float] = Heartbeat._client_durations(futures)
        client_stats: str = Heartbeat.format_duration_stats(client_durations)
        duration_info: str = "  dur/client: " + client_stats
        server_durations: Optional[List[float]] = self._server_durations()
        if server_durations is not None:
            server_stats: str = Heartbeat.format_duration_stats(server_durations)
            duration_info += "  dur/server: " + server_stats
        return duration_info

    def _sample_system_threads(self) -> None:
        """
        Keep the system thread count when it is a new peak.
        """
        current_system_threads: int = SystemResources.total_threads()
        if Heartbeat.is_new_peak(current_system_threads, self._peak_system_threads):
            self._peak_system_threads = current_system_threads

    def _sample_client_rss(self) -> None:
        """
        Sample client RSS and keep it when it is a new peak.
        """
        if self._client_process is None:
            return
        try:
            rss_megabytes: float = self._client_process.memory_info().rss / ResourceMonitor.ONE_MEGABYTE
            if Heartbeat.is_new_peak(rss_megabytes, self._peak_client_rss_megabytes):
                self._peak_client_rss_megabytes = rss_megabytes
        except (NoSuchProcess, AccessDenied):
            pass

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
            memory_info: Any = self._server_process.memory_full_info()
            server_memory["rss_megabytes"] = memory_info.rss / ResourceMonitor.ONE_MEGABYTE
            server_memory["swap_megabytes"] = memory_info.swap / ResourceMonitor.ONE_MEGABYTE
        except (NoSuchProcess, AccessDenied):
            server_memory["rss_megabytes"] = None
            server_memory["swap_megabytes"] = None
        return server_memory

    def _check_server_alive(self) -> bool:
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

    def _check_memory_warnings(self, swap_megabytes: float) -> None:
        """
        Warn if system memory or swap exceeds thresholds.

        :param swap_megabytes: Server swap in MB
        """
        self._check_system_memory_warning()
        if not self._swap_warned and swap_megabytes > 0:
            self._swap_warned = True
            warning: str = (f"  WARNING: Server has {Formatters.format_rss(swap_megabytes)} swapped to disk"
                            " — severe performance impact")
            self.logger.warning("%s", warning)
            self._write_to_file(warning)

    def _check_system_memory_warning(self) -> None:
        """
        Warn when total system memory usage exceeds threshold.

        """
        if self._out_of_memory_warned:
            return
        virtual_memory_stats: Any = virtual_memory()
        used_fraction: float = virtual_memory_stats.percent / 100.0
        if used_fraction >= OUT_OF_MEMORY_WARNING_THRESHOLD:
            self._out_of_memory_warned = True
            total_gigabytes: float = virtual_memory_stats.total / ResourceMonitor.ONE_GIGABYTE
            available_gigabytes: float = virtual_memory_stats.available / ResourceMonitor.ONE_GIGABYTE
            warning: str = (f"  WARNING: System memory at {virtual_memory_stats.percent:.0f}%"
                            f" ({available_gigabytes:.1f} GB free / {total_gigabytes:.1f} GB total) — risk of OOM kill")
            self.logger.warning("%s", warning)
            self._write_to_file(warning)
            swap_memory_stats: Any = swap_memory()
            if swap_memory_stats.total > 0 and swap_memory_stats.used > 0:
                swap_used_gigabytes: float = swap_memory_stats.used / ResourceMonitor.ONE_GIGABYTE
                swap_warning: str = (f"  WARNING: System swap in use: {swap_used_gigabytes:.1f} GB"
                                     " — severe performance impact")
                self.logger.warning("%s", swap_warning)
                self._write_to_file(swap_warning)

    @staticmethod
    def _format_system_memory() -> Dict[str, Any]:
        """
        Format total system memory usage for the progress line.

        :return: Dict with "text" (the progress line part), "memory_percent" and "available_gigabytes"
        """
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
        if self._peak_system_memory is not None:
            peak_memory_percent = self._peak_system_memory.get("memory_percent")
        if Heartbeat.is_new_peak(memory_percent, peak_memory_percent):
            self._peak_system_memory = {"memory_percent": memory_percent, "available_gigabytes": available_gigabytes}

    def _format_system_cpu(self) -> str:
        """
        Format whole-box CPU utilization with peak-so-far.

        Uses non-blocking ``cpu_percent`` (usage since the previous
        sample) and tracks the peak across the run.  0-100% across
        all cores.

        :return: The CPU part of the progress line
        """
        current_cpu_percent: float = cpu_percent(interval=None)
        # Unlike the other peaks, a 0% first reading is kept, so every tick reports a CPU peak.
        if self._peak_system_cpu_percent is None:
            self._peak_system_cpu_percent = current_cpu_percent
        self._peak_system_cpu_percent = max(self._peak_system_cpu_percent, current_cpu_percent)
        return f"  syscpu: {current_cpu_percent:.0f}% (peak {self._peak_system_cpu_percent:.0f}%)"

    @staticmethod
    def _percent(part: int, whole: int) -> int:
        """
        Work out part as a whole-number percent of whole.

        :param part: Count to express as a percent
        :param whole: Count that is 100%
        :return: The whole-number percent, or 0 when whole is 0 or less
        """
        if whole <= 0:
            return 0
        return int(part * 100 / whole)

    @staticmethod
    def _count_done(futures: List[Future]) -> int:
        """
        Count the requests that have finished.

        :param futures: Futures of the requests fired in this stage
        :return: Number of futures that are done
        """
        done_count: int = 0
        future: Future
        # Count the futures that are done.
        for future in futures:
            if future.done():
                done_count += 1
        return done_count

    @staticmethod
    def _client_durations(futures: List[Future]) -> List[float]:
        """
        Collect per-request wall-time for completed futures.

        Reads only already-done futures (non-blocking) and skips
        cancelled ones or ones that raised, so a failed request
        can never break the heartbeat line.

        :param futures: Futures of the requests fired in this stage
        :return: Durations in seconds of the finished requests
        """
        durations: List[float] = []
        future: Future
        # Read the elapsed time of each request that finished without an error.
        for future in futures:
            if not future.done() or future.cancelled():
                continue
            result: Dict[str, Any] = {}
            try:
                if future.exception() is not None:
                    continue
                result = future.result()
            except (CancelledError, FutureTimeoutError):
                continue
            duration_seconds: Optional[float] = result.get("elapsed", result.get("duration"))
            if isinstance(duration_seconds, (int, float)) and duration_seconds > 0:
                durations.append(float(duration_seconds))
        return durations

    def _server_durations(self) -> Optional[List[float]]:
        """
        Collect cumulative server-side per-request durations.

        Parses primary streaming_chat Start/Finish pairs from the
        server log since the stage start position.

        :return: Durations in seconds, or None when no server log is available
                 (so the caller can render ``n/a`` and distinguish "no data source" from "no requests yet")
        """
        if self._log_monitor is None or self._log_start_position is None:
            return None
        pairs: List[Dict[str, object]] = []
        try:
            pairs = self._log_monitor.parse_streaming_chat_timing_since(self._log_start_position)
        except (OSError, ValueError):
            return []
        durations: List[float] = []
        pair: Dict[str, object]
        # Keep the duration of each primary agent Start/Finish pair.
        for pair in pairs:
            if self._primary_start_regex is not None:
                agent: object = pair.get("agent", "")
                start_line: str = f"Start {agent}/streaming_chat"
                if not self._primary_start_regex.search(start_line):
                    continue
            duration_seconds: object = pair.get("duration_seconds")
            if isinstance(duration_seconds, (int, float)) and duration_seconds > 0:
                durations.append(float(duration_seconds))
        return durations

    def _sample_server_metrics(self) -> Dict[str, str]:
        """
        Sample server thread count and RSS, keeping each when it is a new peak.

        :return: Dict with "thread_info" and "server_rss_info", the parts of the progress line
        """
        thread_info: str = ""
        server_rss_info: str = ""
        if self._server_process is None:
            return Heartbeat._server_metrics(thread_info, server_rss_info)
        try:
            server_thread_count: int = self._server_process.num_threads()
            if Heartbeat.is_new_peak(server_thread_count, self._peak_server_threads):
                self._peak_server_threads = server_thread_count
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
                swap_info = f" swap: {Formatters.format_rss(swap_megabytes)}"
            server_rss_info = f"  RSS: {Formatters.format_rss(rss_megabytes)}{swap_info}"
            if Heartbeat.is_new_peak(rss_megabytes, self._peak_server_rss_megabytes):
                self._peak_server_rss_megabytes = rss_megabytes
            self._check_memory_warnings(swap_megabytes)
        return Heartbeat._server_metrics(thread_info, server_rss_info)

    @staticmethod
    def _server_metrics(thread_info: str, server_rss_info: str) -> Dict[str, str]:
        """
        Put the server parts of the progress line in the dict _sample_server_metrics() returns.

        :param thread_info: Thread count text, or ""
        :param server_rss_info: RSS and swap text, or ""
        :return: Dict with "thread_info" and "server_rss_info"
        """
        server_metrics: Dict[str, str] = {
            "thread_info": thread_info,
            "server_rss_info": server_rss_info,
        }
        return server_metrics

    def _write_to_file(self, line: str, end: str = "\n") -> None:
        """
        Append a line to progress.log, when output_dir is set.

        The file is opened for each line in append mode, so the request lines TrafficRunner writes there stay.

        :param line: The line to write
        :param end: Text written after the line. progress_heartbeat() writes "" with end "" to create the file
            before the first tick, so a stage with no tick still leaves an empty progress.log.
        """
        if not self._output_dir:
            return
        path: str = join(self._output_dir, LoadTestConstants.PROGRESS_LOG_FILE_NAME)
        file_line: str = line + end
        with open(path, "a", encoding="utf-8") as progress_file:
            progress_file.write(file_line)

    def _write_to_console(self, tick_count: int, line: str, force: bool = False) -> None:
        """
        Write progress to console.

        Prints the full line on tick 1, then every
        ``CONSOLE_INTERVAL_TICKS`` ticks (currently every tick), and
        always when ``force`` is set (e.g. the final line once all
        requests are done).  A single blank separator is emitted only
        before the first console line so the heartbeats are
        single-spaced thereafter.

        :param tick_count: Number of heartbeat ticks so far
        :param line: The progress line
        :param force: Write the line even when this tick would be skipped
        """
        if (force
                or tick_count == 1
                or tick_count % CONSOLE_INTERVAL_TICKS == 0):
            if not self._console_started:
                sys.stdout.write("\n")
                self._console_started = True
            self.logger.info("%s", line)
