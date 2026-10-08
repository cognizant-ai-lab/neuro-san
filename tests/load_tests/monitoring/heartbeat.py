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

"""Progress heartbeat — periodic logging while requests are in-flight.

Interim implementation. May be replaced by neuro-san built-in
monitoring and telemetry when those features become available.
"""

import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import CancelledError
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import TextIO
from typing import Tuple

import psutil

from tests.load_tests.config import HEARTBEAT_INTERVAL_SECONDS
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.system_resources import SystemResources

logger: logging.Logger = logging.getLogger(__name__)

CONSOLE_TICK_INTERVAL: int = 1
OUT_OF_MEMORY_WARNING_THRESHOLD: float = 0.80


class Heartbeat:  # pylint: disable=too-many-instance-attributes
    """Logs periodic progress while requests are in-flight.

    Holds the server process handle so the heartbeat thread can
    read thread counts without the caller passing it each time.

    Also keeps the stage's peak readings. The heartbeat thread writes
    them; read them with the get_peak_*() methods after join().
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
            self, server_proc: Optional[psutil.Process],
            client_proc: Optional[psutil.Process] = None,
            output_dir: Optional[str] = None,
            log_monitor: Optional[ServerLogMonitor] = None,
            log_start_pos: Optional[int] = None,
            primary_start_pattern: Optional[str] = None,
    ) -> None:
        """
        Constructor.

        :param server_proc: Server process for thread count and RSS readings, or None
        :param client_proc: Client process for RSS readings, or None
        :param output_dir: Directory for progress.log, or None for console only
        :param log_monitor: Server log reader for server-side request timing, or None
        :param log_start_pos: Server log offset where the stage started, or None
        :param primary_start_pattern: Regex for the log line of a primary agent request starting, or None
        """
        self._server_proc: Optional[psutil.Process] = server_proc
        self._client_proc: Optional[psutil.Process] = client_proc
        self._output_dir: Optional[str] = output_dir
        self._total_system_ram: int = psutil.virtual_memory().total
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
        self._failed_request_lock: threading.Lock = threading.Lock()
        # Prime the non-blocking system CPU counter so the first real
        # sample reflects usage since the heartbeat started rather
        # than returning 0.0.
        psutil.cpu_percent(interval=None)
        # Optional server-log source for per-request server-side
        # timing.  When set, the heartbeat parses primary
        # streaming_chat Start/Finish pairs to report cumulative
        # server-side min/avg/max durations.
        self._log_monitor: Optional[ServerLogMonitor] = log_monitor
        self._log_start_pos: Optional[int] = log_start_pos
        self._primary_start_re: Optional[re.Pattern] = None
        if primary_start_pattern:
            self._primary_start_re = re.compile(primary_start_pattern)

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

    def _sample_client_rss(self) -> None:
        """
        Sample client RSS and keep it when it is a new peak.
        """
        if self._client_proc is None:
            return
        try:
            rss_megabytes: float = self._client_proc.memory_info().rss / (1024 * 1024)
            if Heartbeat.is_new_peak(rss_megabytes, self._peak_client_rss_megabytes):
                self._peak_client_rss_megabytes = rss_megabytes
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def _sample_server_memory(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Sample server RSS and swap in MB.

        :return: (rss_megabytes, swap_megabytes), or (None, None) if unavailable
        """
        if self._server_proc is None:
            return None, None
        try:
            memory_info: Any = self._server_proc.memory_full_info()
            rss_megabytes: float = memory_info.rss / (1024 * 1024)
            swap_megabytes: float = memory_info.swap / (1024 * 1024)
            return rss_megabytes, swap_megabytes
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None, None

    def _check_server_alive(self) -> bool:
        """
        Tell whether the server process is still running.

        :return: True if the server process is still running
        """
        if self._server_proc is None:
            return True
        try:
            return self._server_proc.is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def _check_memory_warnings(self, swap_megabytes: float, progress_file: Optional[TextIO]) -> None:
        """
        Warn if system memory or swap exceeds thresholds.

        :param swap_megabytes: Server swap in MB
        :param progress_file: Open progress.log, or None
        """
        self._check_system_memory_warning(progress_file)
        if not self._swap_warned and swap_megabytes > 0:
            self._swap_warned = True
            warning: str = (f"  WARNING: Server has {Formatters.format_rss(swap_megabytes)} swapped to disk"
                            " — severe performance impact")
            logger.warning("%s", warning)
            self._write_to_file(progress_file, warning)

    def _check_system_memory_warning(self, progress_file: Optional[TextIO]) -> None:
        """
        Warn when total system memory usage exceeds threshold.

        :param progress_file: Open progress.log, or None
        """
        if self._out_of_memory_warned:
            return
        virtual_memory_stats: Any = psutil.virtual_memory()
        used_fraction: float = virtual_memory_stats.percent / 100.0
        if used_fraction >= OUT_OF_MEMORY_WARNING_THRESHOLD:
            self._out_of_memory_warned = True
            total_gigabytes: float = virtual_memory_stats.total / (1024 ** 3)
            available_gigabytes: float = virtual_memory_stats.available / (1024 ** 3)
            warning: str = (f"  WARNING: System memory at {virtual_memory_stats.percent:.0f}%"
                            f" ({available_gigabytes:.1f}G free / {total_gigabytes:.1f}G total) — risk of OOM kill")
            logger.warning("%s", warning)
            self._write_to_file(progress_file, warning)
            swap: Any = psutil.swap_memory()
            if swap.total > 0 and swap.used > 0:
                swap_used_gigabytes: float = swap.used / (1024 ** 3)
                swap_warning: str = (f"  WARNING: System swap in use: {swap_used_gigabytes:.1f}G"
                                     " — severe performance impact")
                logger.warning("%s", swap_warning)
                self._write_to_file(progress_file, swap_warning)

    # pylint: disable=too-many-locals,too-many-arguments
    # pylint: disable=too-many-statements
    def progress_heartbeat(self, futures: List[Future], total: int, start_seconds: float, stop_event: threading.Event,
                           ready_event: threading.Event, fires_done_event: threading.Event,
                           server_dead_event: threading.Event) -> None:
        """
        Log periodic progress while requests are in-flight.

        Signals ready_event after the initial RSS sample so the
        caller can wait for the heartbeat to be ready before
        firing requests.  Waits for fires_done_event before
        printing progress so ticks do not overlap receipt dots.

        :param futures: Futures of the requests fired in this stage
        :param total: Number of requests in this stage
        :param start_seconds: time.perf_counter() value taken when the stage began
        :param stop_event: Set by the caller to stop the heartbeat
        :param ready_event: Set once the initial RSS sample is taken
        :param fires_done_event: Set by the caller once every request is fired
        :param server_dead_event: Set when the server process is found dead
        """
        last_done: int = 0
        last_change_seconds: float = start_seconds
        tick_count: int = 0
        self._sample_client_rss()
        ready_event.set()
        fires_done_event.wait()
        progress_file: Optional[TextIO] = self._open_progress_file()
        try:
            while True:
                stopped: bool = stop_event.wait(timeout=HEARTBEAT_INTERVAL_SECONDS)
                if not stopped and not self._check_server_alive():
                    logger.error("\n  ABORT: Server process is no longer running. Possible OOM kill.")
                    server_dead_event.set()
                    break
                self._sample_client_rss()
                done: int = Heartbeat._count_done(futures)
                elapsed_seconds: int = int(time.perf_counter() - start_seconds)
                timestamp: str = time.strftime("%H:%M:%S", time.localtime())
                percent_done: int = Heartbeat._percent(done, total)
                suffix: str = ""
                in_flight: int = total - done
                if done == last_done and done < total:
                    stall_seconds: int = int(time.perf_counter() - last_change_seconds)
                    suffix = f"  !! {in_flight} request(s) stalled for {Heartbeat._fmt_elapsed(stall_seconds)}"
                if done > last_done:
                    last_change_seconds = time.perf_counter()
                    last_done = done
                thread_info: str = ""
                server_rss_info: str = ""
                thread_info, server_rss_info = self._sample_server_metrics(progress_file)
                tick_count += 1
                failed: int = self.get_failed_request_count()
                fail_info: str = ""
                if failed > 0:
                    failed_percent: int = Heartbeat._percent(failed, done)
                    fail_info = f", {failed} failed {failed_percent}%"
                system_memory_info: str = ""
                current_memory_percent: float = 0.0
                current_available_gigabytes: float = 0.0
                system_memory_info, current_memory_percent, current_available_gigabytes = self._format_system_memory()
                self._sample_system_memory(current_memory_percent, current_available_gigabytes)
                client_durations: List[float] = Heartbeat._client_durations(futures)
                duration_info: str = "  dur/client: " + Heartbeat.format_dur_stats(client_durations)
                server_durations: Optional[List[float]] = self._server_durations()
                if server_durations is not None:
                    duration_info += "  dur/server: " + Heartbeat.format_dur_stats(server_durations)
                system_cpu_info: str = self._format_system_cpu()
                current_system_threads: int = SystemResources.total_threads()
                if Heartbeat.is_new_peak(current_system_threads, self._peak_system_threads):
                    self._peak_system_threads = current_system_threads
                line: str = (f"  [progress] {done} of {total} completed ({percent_done}%{fail_info}) --"
                             f" {Heartbeat._fmt_elapsed(elapsed_seconds)} elapsed [{timestamp}]{suffix}"
                             f"  {duration_info.strip()}{thread_info}{server_rss_info}"
                             f"{system_memory_info}{system_cpu_info}")
                self._write_to_file(progress_file, line)
                self._write_to_console(tick_count, line, force=stopped)
                if stopped:
                    break
        finally:
            if progress_file is not None:
                progress_file.close()

    @staticmethod
    def _format_system_memory() -> Tuple[str, float, float]:
        """
        Format total system memory usage for the progress line.

        :return: (formatted_string, current_percent, available_gigabytes)
        """
        virtual_memory_stats: Any = psutil.virtual_memory()
        used_megabytes: float = (virtual_memory_stats.total - virtual_memory_stats.available) / (1024 ** 2)
        available_gigabytes: float = virtual_memory_stats.available / (1024 ** 3)
        line: str = (f"  sysmem: {virtual_memory_stats.percent:.0f}%"
                     f" ({used_megabytes:.0f}M used / {available_gigabytes:.1f}G free)")
        return line, virtual_memory_stats.percent, available_gigabytes

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
        current_cpu_percent: float = psutil.cpu_percent(interval=None)
        # Unlike the other peaks, a 0% first reading is kept, so every tick reports a CPU peak.
        if self._peak_system_cpu_percent is None:
            self._peak_system_cpu_percent = current_cpu_percent
        self._peak_system_cpu_percent = max(self._peak_system_cpu_percent, current_cpu_percent)
        return f"  syscpu: {current_cpu_percent:.0f}% (peak {self._peak_system_cpu_percent:.0f}%)"

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
    def _fmt_elapsed(seconds: int) -> str:
        """
        Format seconds with minutes when >= 60.

        :param seconds: Elapsed seconds
        :return: The formatted duration
        """
        if seconds >= 60:
            return f"{seconds}s ({seconds // 60}m)"
        return f"{seconds}s"

    @staticmethod
    def format_dur_stats(durations: List[float]) -> str:
        """
        Format cumulative min/avg/max over durations.

        :param durations: Request durations in seconds
        :return: The min/avg/max text, or "n/a" when there are no durations yet
        """
        if not durations:
            return "n/a"
        min_seconds: int = int(min(durations))
        max_seconds: int = int(max(durations))
        average_seconds: int = int(sum(durations) / len(durations))
        return (f"{Heartbeat._fmt_elapsed(min_seconds)} min / {Heartbeat._fmt_elapsed(average_seconds)} avg /"
                f" {Heartbeat._fmt_elapsed(max_seconds)} max")

    @staticmethod
    def _count_done(futures: List[Future]) -> int:
        """
        Count the requests that have finished.

        :param futures: Futures of the requests fired in this stage
        :return: Number of futures that are done
        """
        done: int = 0
        for future in futures:
            if future.done():
                done += 1
        return done

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
        if self._log_monitor is None or self._log_start_pos is None:
            return None
        pairs: List[Dict[str, object]] = []
        try:
            pairs = self._log_monitor.parse_streaming_chat_timing_since(self._log_start_pos)
        except (OSError, ValueError):
            return []
        durations: List[float] = []
        for pair in pairs:
            if self._primary_start_re is not None:
                agent: object = pair.get("agent", "")
                start_line: str = f"Start {agent}/streaming_chat"
                if not self._primary_start_re.search(start_line):
                    continue
            duration_seconds: object = pair.get("duration_seconds")
            if isinstance(duration_seconds, (int, float)) and duration_seconds > 0:
                durations.append(float(duration_seconds))
        return durations

    def _sample_server_metrics(self, progress_file: Optional[TextIO]) -> Tuple[str, str]:
        """
        Sample server thread count and RSS, keeping each when it is a new peak.

        :param progress_file: Open progress.log, or None
        :return: (thread_info, server_rss_info) parts of the progress line
        """
        thread_info: str = ""
        server_rss_info: str = ""
        if self._server_proc is None:
            return thread_info, server_rss_info
        try:
            threads: int = self._server_proc.num_threads()
            if Heartbeat.is_new_peak(threads, self._peak_server_threads):
                self._peak_server_threads = threads
                thread_info = f"  threads: {threads} (peak)"
            else:
                thread_info = f"  threads: {threads}"
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            logger.debug("Heartbeat thread count unavailable: %s", exc)
        rss_megabytes: Optional[float] = None
        swap_megabytes: Optional[float] = None
        rss_megabytes, swap_megabytes = self._sample_server_memory()
        if rss_megabytes is not None:
            swap_info: str = ""
            if swap_megabytes > 0:
                swap_info = f" swap: {Formatters.format_rss(swap_megabytes)}"
            server_rss_info = f"  RSS: {Formatters.format_rss(rss_megabytes)}{swap_info}"
            if Heartbeat.is_new_peak(rss_megabytes, self._peak_server_rss_megabytes):
                self._peak_server_rss_megabytes = rss_megabytes
            self._check_memory_warnings(swap_megabytes, progress_file)
        return thread_info, server_rss_info

    def _open_progress_file(self) -> Optional[TextIO]:
        """
        Open progress.log for writing if output_dir is set.

        :return: The open progress.log, or None when there is no output_dir
        """
        if not self._output_dir:
            return None
        path: str = os.path.join(self._output_dir, "progress.log")
        # pylint: disable=consider-using-with
        return open(path, "w", encoding="utf-8")

    @staticmethod
    def _write_to_file(progress_file: Optional[TextIO], line: str) -> None:
        """
        Write a progress line to the file.

        :param progress_file: Open progress.log, or None to skip
        :param line: The progress line
        """
        if progress_file is None:
            return
        progress_file.write(line + "\n")
        progress_file.flush()

    def _write_to_console(self, tick_count: int, line: str, force: bool = False) -> None:
        """
        Write progress to console.

        Prints the full line on tick 1, then every
        ``CONSOLE_TICK_INTERVAL`` ticks (currently every tick), and
        always when ``force`` is set (e.g. the final line once all
        requests are done).  A single blank separator is emitted only
        before the first console line so the heartbeats are
        single-spaced thereafter.

        :param tick_count: Number of heartbeat ticks so far
        :param line: The progress line
        :param force: Write the line even when this tick would be skipped
        """
        if force or tick_count == 1 or tick_count % CONSOLE_TICK_INTERVAL == 0:
            if not self._console_started:
                sys.stdout.write("\n")
                self._console_started = True
            logger.info("%s", line)
