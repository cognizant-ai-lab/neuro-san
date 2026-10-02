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
from tests.load_tests.shared_ref import SharedRef

logger = logging.getLogger(__name__)

CONSOLE_TICK_INTERVAL = 1
OUT_OF_MEMORY_WARNING_THRESHOLD = 0.80


class Heartbeat:  # pylint: disable=too-many-instance-attributes
    """Logs periodic progress while requests are in-flight.

    Holds the server process handle so the heartbeat thread can
    read thread counts without the caller passing it each time.
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
        self._peak_sys_cpu: float = 0.0
        self._console_started: bool = False
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
        self._primary_start_re: Optional[re.Pattern] = (
            re.compile(primary_start_pattern)
            if primary_start_pattern else None
        )

    def _sample_client_rss(self, peak_rss_megabytes: float, peak_ref: SharedRef) -> float:
        """
        Sample client RSS and update the peak if higher.

        :param peak_rss_megabytes: Peak client RSS in MB so far
        :param peak_ref: Receives the new peak when this sample is higher
        :return: The peak client RSS in MB after this sample
        """
        if self._client_proc is None:
            return peak_rss_megabytes
        try:
            rss_megabytes: float = (
                self._client_proc.memory_info().rss / (1024 * 1024)
            )
            if rss_megabytes > peak_rss_megabytes:
                peak_rss_megabytes = rss_megabytes
                peak_ref.value = rss_megabytes
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return peak_rss_megabytes

    def _sample_server_memory(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Sample server RSS and swap in MB.

        :return: (rss_megabytes, swap_megabytes), or (None, None) if unavailable
        """
        if self._server_proc is None:
            return None, None
        try:
            info = self._server_proc.memory_full_info()
            rss_megabytes: float = info.rss / (1024 * 1024)
            swap_megabytes: float = info.swap / (1024 * 1024)
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
            warning = (
                f"  WARNING: Server has"
                f" {Formatters.format_rss(swap_megabytes)} swapped to disk"
                " — severe performance impact"
            )
            logger.warning("%s", warning)
            self._write_to_file(progress_file, warning)

    def _check_system_memory_warning(self, progress_file: Optional[TextIO]) -> None:
        """
        Warn when total system memory usage exceeds threshold.

        :param progress_file: Open progress.log, or None
        """
        if self._out_of_memory_warned:
            return
        virtual_memory_stats = psutil.virtual_memory()
        used_fraction = virtual_memory_stats.percent / 100.0
        if used_fraction >= OUT_OF_MEMORY_WARNING_THRESHOLD:
            self._out_of_memory_warned = True
            total_gigabytes = virtual_memory_stats.total / (1024 ** 3)
            available_gigabytes = virtual_memory_stats.available / (1024 ** 3)
            warning = (
                f"  WARNING: System memory at"
                f" {virtual_memory_stats.percent:.0f}%"
                f" ({available_gigabytes:.1f}G free"
                f" / {total_gigabytes:.1f}G total)"
                " — risk of OOM kill"
            )
            logger.warning("%s", warning)
            self._write_to_file(progress_file, warning)
            swap = psutil.swap_memory()
            if swap.total > 0 and swap.used > 0:
                swap_used_gigabytes = swap.used / (1024 ** 3)
                swap_warning = (
                    f"  WARNING: System swap in use:"
                    f" {swap_used_gigabytes:.1f}G"
                    " — severe performance impact"
                )
                logger.warning("%s", swap_warning)
                self._write_to_file(
                    progress_file, swap_warning,
                )

    # pylint: disable=too-many-locals,too-many-arguments
    # pylint: disable=too-many-statements
    def progress_heartbeat(self, futures: List[Future], total: int, start_seconds: float,
                           stop_event: threading.Event,
                           ready_event: threading.Event,
                           fires_done_event: threading.Event,
                           peak_threads_ref: SharedRef,
                           peak_client_rss_ref: SharedRef,
                           peak_server_rss_ref: SharedRef,
                           peak_sys_mem_pct_ref: SharedRef,
                           peak_sys_cpu_ref: SharedRef,
                           peak_sys_threads_ref: SharedRef,
                           failed_ref: SharedRef,
                           server_dead_event: threading.Event,
                           ) -> None:
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
        :param peak_threads_ref: Receives the peak server thread count
        :param peak_client_rss_ref: Receives the peak client RSS in MB
        :param peak_server_rss_ref: Receives the peak server RSS in MB
        :param peak_sys_mem_pct_ref: Receives the peak system memory usage in percent
        :param peak_sys_cpu_ref: Receives the peak system CPU usage in percent
        :param peak_sys_threads_ref: Receives the peak system thread count
        :param failed_ref: Shared counter of failed requests
        :param server_dead_event: Set when the server process is found dead
        """
        last_done = 0
        last_change_seconds = start_seconds
        peak_threads = 0
        peak_server_rss_megabytes = 0.0
        peak_system_memory_percent = 0.0
        peak_sys_threads = 0
        tick_count = 0
        peak_client_rss_megabytes = self._sample_client_rss(0.0, peak_client_rss_ref)
        ready_event.set()
        fires_done_event.wait()
        progress_file: Optional[TextIO] = self._open_progress_file()
        try:
            while True:
                stopped: bool = stop_event.wait(
                    timeout=HEARTBEAT_INTERVAL_SECONDS,
                )
                if not stopped and not self._check_server_alive():
                    logger.error(
                        "\n  ABORT: Server process is no longer"
                        " running. Possible OOM kill.",
                    )
                    server_dead_event.set()
                    break
                peak_client_rss_megabytes = self._sample_client_rss(
                    peak_client_rss_megabytes, peak_client_rss_ref,
                )
                done: int = Heartbeat._count_done(futures)
                elapsed_seconds: int = int(time.perf_counter() - start_seconds)
                ts = time.strftime("%H:%M:%S", time.localtime())
                percent_done = done * 100 // total if total > 0 else 0
                suffix = ""
                in_flight = total - done
                if done == last_done and done < total:
                    stall_seconds: int = int(time.perf_counter() - last_change_seconds)
                    suffix = (
                        f"  !! {in_flight} request(s) stalled for "
                        f"{Heartbeat._fmt_elapsed(stall_seconds)}"
                    )
                if done > last_done:
                    last_change_seconds = time.perf_counter()
                    last_done = done
                thread_info: str
                server_rss_info: str
                thread_info, server_rss_info = (
                    self._sample_server_metrics(
                        peak_threads, peak_threads_ref,
                        peak_server_rss_megabytes, peak_server_rss_ref,
                        progress_file,
                    )
                )
                peak_threads = peak_threads_ref.value or 0
                if peak_server_rss_ref.value is not None:
                    peak_server_rss_megabytes = peak_server_rss_ref.value
                tick_count += 1
                failed: int = failed_ref.value or 0
                fail_info = ""
                if failed > 0:
                    failed_percent = failed * 100 // done if done else 0
                    fail_info = (
                        f", {failed} failed {failed_percent}%"
                    )
                sys_mem_info: str
                current_memory_percent: float
                current_available_gigabytes: float
                sys_mem_info, current_memory_percent, current_available_gigabytes = (
                    self._format_system_memory()
                )
                if current_memory_percent > peak_system_memory_percent:
                    peak_system_memory_percent = current_memory_percent
                    peak_sys_mem_pct_ref.value = {
                        "pct": current_memory_percent,
                        "avail_gb": current_available_gigabytes,
                    }
                dur_info = (
                    "  dur/client: "
                    + Heartbeat.format_dur_stats(
                        Heartbeat._client_durations(futures),
                    )
                )
                server_durs: Optional[List[float]] = self._server_durations()
                if server_durs is not None:
                    dur_info += (
                        "  dur/server: "
                        + Heartbeat.format_dur_stats(server_durs)
                    )
                sys_cpu_info = self._format_system_cpu()
                peak_sys_cpu_ref.value = self._peak_sys_cpu
                cur_sys_threads: int = SystemResources.total_threads()
                if cur_sys_threads > peak_sys_threads:
                    peak_sys_threads = cur_sys_threads
                    peak_sys_threads_ref.value = cur_sys_threads
                line = (
                    f"  [progress] {done} of {total} completed"
                    f" ({percent_done}%{fail_info}) --"
                    f" {Heartbeat._fmt_elapsed(elapsed_seconds)}"
                    f" elapsed [{ts}]{suffix}  {dur_info.strip()}"
                    f"{thread_info}"
                    f"{server_rss_info}{sys_mem_info}{sys_cpu_info}"
                )
                self._write_to_file(progress_file, line)
                self._write_to_console(
                    tick_count, line, force=stopped,
                )
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
        virtual_memory_stats = psutil.virtual_memory()
        used_megabytes = (virtual_memory_stats.total - virtual_memory_stats.available) / (1024 ** 2)
        available_gigabytes = virtual_memory_stats.available / (1024 ** 3)
        return (
            f"  sysmem: {virtual_memory_stats.percent:.0f}%"
            f" ({used_megabytes:.0f}M used / {available_gigabytes:.1f}G free)",
            virtual_memory_stats.percent,
            available_gigabytes,
        )

    def _format_system_cpu(self) -> str:
        """
        Format whole-box CPU utilization with peak-so-far.

        Uses non-blocking ``cpu_percent`` (usage since the previous
        sample) and tracks the peak across the run.  0-100% across
        all cores.

        :return: The CPU part of the progress line
        """
        current_cpu_percent: float = psutil.cpu_percent(interval=None)
        self._peak_sys_cpu = max(self._peak_sys_cpu, current_cpu_percent)
        return f"  syscpu: {current_cpu_percent:.0f}% (peak {self._peak_sys_cpu:.0f}%)"

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
        min_seconds = int(min(durations))
        max_seconds = int(max(durations))
        average_seconds = int(sum(durations) / len(durations))
        return (
            f"{Heartbeat._fmt_elapsed(min_seconds)} min /"
            f" {Heartbeat._fmt_elapsed(average_seconds)} avg /"
            f" {Heartbeat._fmt_elapsed(max_seconds)} max"
        )

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
            try:
                if future.exception() is not None:
                    continue
                result = future.result()
            except (CancelledError, FutureTimeoutError):
                continue
            duration_seconds = result.get("elapsed", result.get("duration"))
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
        try:
            pairs: List[Dict[str, object]] = self._log_monitor.parse_streaming_chat_timing_since(
                self._log_start_pos,
            )
        except (OSError, ValueError):
            return []
        durations: List[float] = []
        for pair in pairs:
            if self._primary_start_re is not None:
                agent = pair.get("agent", "")
                start_line = f"Start {agent}/streaming_chat"
                if not self._primary_start_re.search(start_line):
                    continue
            duration_seconds = pair.get("duration_seconds")
            if isinstance(duration_seconds, (int, float)) and duration_seconds > 0:
                durations.append(float(duration_seconds))
        return durations

    # pylint: disable=too-many-positional-arguments
    def _sample_server_metrics(self, peak_threads: int, peak_threads_ref: SharedRef, peak_server_rss_megabytes: float,
                               peak_server_rss_ref: SharedRef, progress_file: Optional[TextIO]) -> Tuple[str, str]:
        """
        Sample server thread count and RSS.

        :param peak_threads: Peak server thread count so far
        :param peak_threads_ref: Receives the new peak thread count when this sample is higher
        :param peak_server_rss_megabytes: Peak server RSS in MB so far
        :param peak_server_rss_ref: Receives the new peak RSS when this sample is higher
        :param progress_file: Open progress.log, or None
        :return: (thread_info, server_rss_info) parts of the progress line
        """
        thread_info = ""
        server_rss_info = ""
        if self._server_proc is None:
            return thread_info, server_rss_info
        try:
            threads: int = self._server_proc.num_threads()
            if threads > peak_threads:
                peak_threads_ref.value = threads
                thread_info = (
                    f"  threads: {threads} (peak)"
                )
            else:
                thread_info = f"  threads: {threads}"
        except (
            psutil.NoSuchProcess, psutil.AccessDenied,
        ) as exc:
            logger.debug(
                "Heartbeat thread count unavailable: %s",
                exc,
            )
        rss_megabytes, swap_megabytes = self._sample_server_memory()
        if rss_megabytes is not None:
            swap_info = ""
            if swap_megabytes > 0:
                swap_info = f" swap: {Formatters.format_rss(swap_megabytes)}"
            server_rss_info = (
                f"  RSS: {Formatters.format_rss(rss_megabytes)}{swap_info}"
            )
            if rss_megabytes > peak_server_rss_megabytes:
                peak_server_rss_ref.value = rss_megabytes
            self._check_memory_warnings(
                swap_megabytes, progress_file,
            )
        return thread_info, server_rss_info

    def _open_progress_file(self) -> Optional[TextIO]:
        """
        Open progress.log for writing if output_dir is set.

        :return: The open progress.log, or None when there is no output_dir
        """
        if not self._output_dir:
            return None
        path = os.path.join(self._output_dir, "progress.log")
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
        if (force or tick_count == 1
                or tick_count % CONSOLE_TICK_INTERVAL == 0):
            if not self._console_started:
                sys.stdout.write("\n")
                self._console_started = True
            logger.info("%s", line)
