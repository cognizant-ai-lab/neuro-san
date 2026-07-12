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
from typing import List
from typing import Optional

import psutil

from tests.load_tests.config import format_rss
from tests.load_tests.config import HEARTBEAT_INTERVAL_SECONDS
from tests.load_tests.config import SharedRef

logger = logging.getLogger(__name__)

CONSOLE_TICK_INTERVAL = 1
OOM_WARNING_THRESHOLD = 0.80


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
            log_monitor=None,
            log_start_pos=None,
            primary_start_pattern: Optional[str] = None,
    ) -> None:
        self._server_proc = server_proc
        self._client_proc = client_proc
        self._output_dir = output_dir
        self._total_system_ram = psutil.virtual_memory().total
        self._oom_warned = False
        self._swap_warned = False
        self._peak_sys_cpu = 0.0
        # Prime the non-blocking system CPU counter so the first real
        # sample reflects usage since the heartbeat started rather
        # than returning 0.0.
        psutil.cpu_percent(interval=None)
        # Optional server-log source for per-request server-side
        # timing.  When set, the heartbeat parses primary
        # streaming_chat Start/Finish pairs to report cumulative
        # server-side min/avg/max durations.
        self._log_monitor = log_monitor
        self._log_start_pos = log_start_pos
        self._primary_start_re = (
            re.compile(primary_start_pattern)
            if primary_start_pattern else None
        )

    def _sample_client_rss(self, peak_rss, peak_ref) -> float:
        """Sample client RSS and update peak if higher.

        Returns the current peak value.
        """
        if self._client_proc is None:
            return peak_rss
        try:
            rss = (
                self._client_proc.memory_info().rss / (1024 * 1024)
            )
            if rss > peak_rss:
                peak_rss = rss
                peak_ref.value = rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return peak_rss

    def _sample_server_memory(self):
        """Sample server RSS and swap in MB.

        Returns (rss_mb, swap_mb) or (None, None) if unavailable.
        """
        if self._server_proc is None:
            return None, None
        try:
            info = self._server_proc.memory_full_info()
            rss_mb = info.rss / (1024 * 1024)
            swap_mb = info.swap / (1024 * 1024)
            return rss_mb, swap_mb
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None, None

    def _check_server_alive(self) -> bool:
        """Return True if the server process is still running."""
        if self._server_proc is None:
            return True
        try:
            return self._server_proc.is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def _check_memory_warnings(
            self, rss_mb, swap_mb, progress_file,
    ) -> None:
        """Warn if system memory or swap exceeds thresholds."""
        self._check_system_memory_warning(progress_file)
        if not self._swap_warned and swap_mb > 0:
            self._swap_warned = True
            warning = (
                f"  WARNING: Server has"
                f" {format_rss(swap_mb)} swapped to disk"
                " — severe performance impact"
            )
            logger.warning("%s", warning)
            self._write_to_file(progress_file, warning)

    def _check_system_memory_warning(
            self, progress_file,
    ) -> None:
        """Warn when total system memory usage exceeds threshold."""
        if self._oom_warned:
            return
        mem = psutil.virtual_memory()
        used_pct = mem.percent / 100.0
        if used_pct >= OOM_WARNING_THRESHOLD:
            self._oom_warned = True
            total_gb = mem.total / (1024 ** 3)
            avail_gb = mem.available / (1024 ** 3)
            warning = (
                f"  WARNING: System memory at"
                f" {mem.percent:.0f}%"
                f" ({avail_gb:.1f}G free"
                f" / {total_gb:.1f}G total)"
                " — risk of OOM kill"
            )
            logger.warning("%s", warning)
            self._write_to_file(progress_file, warning)
            swap = psutil.swap_memory()
            if swap.total > 0 and swap.used > 0:
                swap_gb = swap.used / (1024 ** 3)
                swap_warning = (
                    f"  WARNING: System swap in use:"
                    f" {swap_gb:.1f}G"
                    " — severe performance impact"
                )
                logger.warning("%s", swap_warning)
                self._write_to_file(
                    progress_file, swap_warning,
                )

    # pylint: disable=too-many-locals,too-many-arguments
    # pylint: disable=too-many-statements
    def progress_heartbeat(self, futures, total, start_time,
                           stop_event, *,
                           ready_event: threading.Event,
                           fires_done_event: threading.Event,
                           peak_threads_ref: SharedRef,
                           peak_client_rss_ref: SharedRef,
                           peak_server_rss_ref: SharedRef,
                           peak_sys_mem_pct_ref: SharedRef,
                           failed_ref: SharedRef,
                           server_dead_event: threading.Event,
                           ) -> None:
        """Log periodic progress while requests are in-flight.

        Signals ready_event after the initial RSS sample so the
        caller can wait for the heartbeat to be ready before
        firing requests.  Waits for fires_done_event before
        printing progress so ticks do not overlap receipt dots.
        """
        last_done = 0
        last_change = start_time
        peak_threads = 0
        peak_server_rss = 0.0
        peak_sys_mem_pct = 0.0
        tick_count = 0
        peak_rss = self._sample_client_rss(0.0, peak_client_rss_ref)
        ready_event.set()
        fires_done_event.wait()
        progress_file = self._open_progress_file()
        try:
            while not stop_event.wait(
                timeout=HEARTBEAT_INTERVAL_SECONDS,
            ):
                if not self._check_server_alive():
                    logger.error(
                        "\n  ABORT: Server process is no longer"
                        " running. Possible OOM kill.",
                    )
                    server_dead_event.set()
                    break
                peak_rss = self._sample_client_rss(
                    peak_rss, peak_client_rss_ref,
                )
                done = sum(1 for f in futures if f.done())
                elapsed = int(time.time() - start_time)
                ts = time.strftime("%H:%M:%S", time.localtime())
                pct = done * 100 // total if total > 0 else 0
                suffix = ""
                in_flight = total - done
                if done == last_done and done < total:
                    stall = int(time.time() - last_change)
                    suffix = (
                        f"  !! {in_flight} request(s) stalled for "
                        f"{Heartbeat._fmt_elapsed(stall)}"
                    )
                if done > last_done:
                    last_change = time.time()
                    last_done = done
                thread_info, server_rss_info = (
                    self._sample_server_metrics(
                        peak_threads, peak_threads_ref,
                        peak_server_rss, peak_server_rss_ref,
                        progress_file,
                    )
                )
                peak_threads = peak_threads_ref.value or 0
                if peak_server_rss_ref.value is not None:
                    peak_server_rss = peak_server_rss_ref.value
                tick_count += 1
                failed = failed_ref.value or 0
                fail_info = ""
                if failed > 0:
                    fail_pct = failed * 100 // done if done else 0
                    fail_info = (
                        f", {failed} failed {fail_pct}%"
                    )
                sys_mem_info, cur_pct, cur_avail = (
                    self._format_system_memory()
                )
                if cur_pct > peak_sys_mem_pct:
                    peak_sys_mem_pct = cur_pct
                    peak_sys_mem_pct_ref.value = {
                        "pct": cur_pct,
                        "avail_gb": cur_avail,
                    }
                dur_info = (
                    "  dur/client: "
                    + Heartbeat.format_dur_stats(
                        Heartbeat._client_durations(futures),
                    )
                )
                server_durs = self._server_durations()
                if server_durs is not None:
                    dur_info += (
                        "  dur/server: "
                        + Heartbeat.format_dur_stats(server_durs)
                    )
                sys_cpu_info = self._format_system_cpu()
                line = (
                    f"  [progress] {done} of {total} completed"
                    f" ({pct}%{fail_info}) --"
                    f" {Heartbeat._fmt_elapsed(elapsed)}"
                    f" elapsed [{ts}]{suffix}  {dur_info.strip()}"
                    f"{thread_info}"
                    f"{server_rss_info}{sys_mem_info}{sys_cpu_info}"
                )
                self._write_to_file(progress_file, line)
                self._write_to_console(tick_count, line)
        finally:
            if progress_file is not None:
                progress_file.close()

    @staticmethod
    def _format_system_memory():
        """Format total system memory usage for the progress line.

        Returns (formatted_string, current_percent,
        available_gb).
        """
        mem = psutil.virtual_memory()
        used_mb = (mem.total - mem.available) / (1024 ** 2)
        avail_gb = mem.available / (1024 ** 3)
        return (
            f"  sysmem: {mem.percent:.0f}%"
            f" ({used_mb:.0f}M used / {avail_gb:.1f}G free)",
            mem.percent,
            avail_gb,
        )

    def _format_system_cpu(self) -> str:
        """Format whole-box CPU utilization with peak-so-far.

        Uses non-blocking ``cpu_percent`` (usage since the previous
        sample) and tracks the peak across the run.  0-100% across
        all cores.
        """
        cur = psutil.cpu_percent(interval=None)
        if cur > self._peak_sys_cpu:
            self._peak_sys_cpu = cur
        return f"  syscpu: {cur:.0f}% (peak {self._peak_sys_cpu:.0f}%)"

    @staticmethod
    def _fmt_elapsed(seconds) -> str:
        """Format seconds with minutes when >= 60."""
        if seconds >= 60:
            return f"{seconds}s ({seconds // 60}m)"
        return f"{seconds}s"

    @staticmethod
    def format_dur_stats(durations: List[float]) -> str:
        """Format cumulative min/avg/max over durations (seconds).

        Returns "n/a" when there are no durations yet.
        """
        if not durations:
            return "n/a"
        lo = int(min(durations))
        hi = int(max(durations))
        avg = int(sum(durations) / len(durations))
        return (
            f"{Heartbeat._fmt_elapsed(lo)} min /"
            f" {Heartbeat._fmt_elapsed(avg)} avg /"
            f" {Heartbeat._fmt_elapsed(hi)} max"
        )

    @staticmethod
    def _client_durations(futures) -> List[float]:
        """Collect per-request wall-time for completed futures.

        Reads only already-done futures (non-blocking) and skips
        cancelled ones or ones that raised, so a failed request
        can never break the heartbeat line.
        """
        durations: List[float] = []
        for fut in futures:
            if not fut.done() or fut.cancelled():
                continue
            try:
                if fut.exception() is not None:
                    continue
                result = fut.result()
            except Exception:  # pylint: disable=broad-exception-caught
                continue
            dur = result.get("elapsed", result.get("duration"))
            if isinstance(dur, (int, float)) and dur > 0:
                durations.append(float(dur))
        return durations

    def _server_durations(self) -> Optional[List[float]]:
        """Collect cumulative server-side per-request durations.

        Parses primary streaming_chat Start/Finish pairs from the
        server log since the stage start position.  Returns None
        when no server log is available (so the caller can render
        ``n/a`` and distinguish "no data source" from "no requests
        yet").
        """
        if self._log_monitor is None or self._log_start_pos is None:
            return None
        try:
            pairs = self._log_monitor.parse_streaming_chat_timing_since(
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
            dur = pair.get("duration")
            if isinstance(dur, (int, float)) and dur > 0:
                durations.append(float(dur))
        return durations

    # pylint: disable=too-many-positional-arguments
    def _sample_server_metrics(
            self, peak_threads, peak_threads_ref,
            peak_server_rss, peak_server_rss_ref,
            progress_file,
    ):
        """Sample server thread count and RSS.

        Returns (thread_info, server_rss_info) strings.
        """
        thread_info = ""
        server_rss_info = ""
        if self._server_proc is None:
            return thread_info, server_rss_info
        try:
            threads = self._server_proc.num_threads()
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
        rss_mb, swap_mb = self._sample_server_memory()
        if rss_mb is not None:
            swap_info = ""
            if swap_mb > 0:
                swap_info = f" swap: {format_rss(swap_mb)}"
            server_rss_info = (
                f"  RSS: {format_rss(rss_mb)}{swap_info}"
            )
            if rss_mb > peak_server_rss:
                peak_server_rss_ref.value = rss_mb
            self._check_memory_warnings(
                rss_mb, swap_mb, progress_file,
            )
        return thread_info, server_rss_info

    def _open_progress_file(self):
        """Open progress.log for writing if output_dir is set."""
        if not self._output_dir:
            return None
        path = os.path.join(self._output_dir, "progress.log")
        # pylint: disable=consider-using-with
        return open(path, "w", encoding="utf-8")

    @staticmethod
    def _write_to_file(progress_file, line) -> None:
        """Write a progress line to the file."""
        if progress_file is None:
            return
        progress_file.write(line + "\n")
        progress_file.flush()

    @staticmethod
    def _write_to_console(tick_count, line) -> None:
        """Write progress to console with reduced verbosity.

        Prints the full line on tick 1 and every 10th tick.
        Silent in between to avoid overlapping receipt dots.
        """
        if tick_count == 1 or tick_count % CONSOLE_TICK_INTERVAL == 0:
            sys.stdout.write("\n")
            logger.info("%s", line)
