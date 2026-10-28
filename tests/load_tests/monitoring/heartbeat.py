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

from concurrent.futures import CancelledError
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from logging import Logger
from logging import getLogger
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

from tests.load_tests.monitoring.tracked_process import TrackedProcess
from tests.load_tests.reporting.duration_parser import DurationParser
from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.progress_log_writer import ProgressLogWriter
from tests.load_tests.monitoring.server_duration_reader import ServerDurationReader
from tests.load_tests.monitoring.stage_resource_sampler import StageResourceSampler
from tests.load_tests.monitoring.stall_tracker import StallTracker


class Heartbeat:
    """
    Logs periodic progress while requests are in-flight.

    Builds one progress line per tick: done count, elapsed time, failed and stalled
    requests and request durations. StageResourceSampler takes the resource readings
    and keeps the stage's peaks; read them with the get_peak_*() methods after join(),
    which ask the sampler.
    StallTracker notes when the done count last changed, and ServerDurationReader reads
    the server-side durations from the server log.
    ProgressLogWriter writes the lines to progress.log and the console.

    Interim implementation. May be replaced by neuro-san built-in
    monitoring and telemetry when those features become available.
    """

    def __init__(self, server_process: Optional[TrackedProcess], client_process: Optional[TrackedProcess] = None,
                 output_dir: Optional[str] = None, server_log_timing: Optional[Dict[str, Any]] = None) -> None:
        """
        Constructor.

        :param server_process: Server process for thread count and RSS readings, or None
        :param client_process: Client process for RSS readings, or None
        :param output_dir: Directory for progress.log, or None for console only
        :param server_log_timing: Where to read server-side request timing, or None. A dict with the following
            keys, each of which may be None:
            "log_monitor"            The ServerLogMonitor
            "log_start_position"     Server log offset where the stage started
            "primary_start_pattern"  Regex for the log line of a primary agent request starting
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self._progress_log_writer: ProgressLogWriter = ProgressLogWriter(output_dir)
        self._resource_sampler: StageResourceSampler = StageResourceSampler(server_process, client_process,
                                                                            self._progress_log_writer)
        # Request worker threads add to this while the heartbeat thread reads it.
        self._failed_request_count: int = 0
        self._failed_request_lock: Lock = Lock()
        # Only the heartbeat thread reads and updates the stall tracker.
        self._stall_tracker: StallTracker = StallTracker()
        self._server_duration_reader: ServerDurationReader = ServerDurationReader(server_log_timing)

    def get_peak_server_threads(self) -> Optional[int]:
        """
        Read the stage's highest server thread count from the sampler.

        :return: The highest server thread count of the stage, or None
        """
        return self._resource_sampler.get_peak_server_threads()

    def get_peak_client_rss_megabytes(self) -> Optional[float]:
        """
        Read the stage's highest client RSS in MB from the sampler.

        :return: The highest client RSS of the stage in MB, or None
        """
        return self._resource_sampler.get_peak_client_rss_megabytes()

    def get_peak_server_rss_megabytes(self) -> Optional[float]:
        """
        Read the stage's highest server RSS in MB from the sampler.

        :return: The highest server RSS of the stage in MB, or None
        """
        return self._resource_sampler.get_peak_server_rss_megabytes()

    def get_peak_system_memory(self) -> Optional[Dict[str, float]]:
        """
        Read the stage's highest system memory use from the sampler.

        :return: None before any sample, else a dict read at the highest system memory use of the stage, with
            the following keys:
            "memory_percent"       System memory use in percent
            "available_gigabytes"  Available system memory in GB
        """
        return self._resource_sampler.get_peak_system_memory()

    def get_peak_system_cpu_percent(self) -> Optional[float]:
        """
        Read the stage's highest whole-box CPU use in percent from the sampler.

        :return: The highest whole-box CPU use of the stage in percent, or None
        """
        return self._resource_sampler.get_peak_system_cpu_percent()

    def get_peak_system_threads(self) -> Optional[int]:
        """
        Read the stage's highest system-wide thread count from the sampler.

        :return: The highest system-wide thread count of the stage, or None
        """
        return self._resource_sampler.get_peak_system_threads()

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
        :param events: A dict with the following keys:
            "stop_event"         Set by the caller to stop the heartbeat
            "ready_event"        Set once the initial RSS sample is taken
            "fires_done_event"   Set by the caller once every request is fired
            "server_dead_event"  Set when the server process is found dead
        """
        stop_event: Event = events.get("stop_event")
        ready_event: Event = events.get("ready_event")
        fires_done_event: Event = events.get("fires_done_event")
        server_dead_event: Event = events.get("server_dead_event")
        self._stall_tracker.start(start_seconds)
        tick_count: int = 0
        self._resource_sampler.sample_client_rss()
        ready_event.set()
        fires_done_event.wait()
        self._progress_log_writer.write_to_file("", end="")
        stopped: bool = False
        line: str = ""
        while True:
            stopped = stop_event.wait(timeout=LoadTestConstants.HEARTBEAT_INTERVAL_SECONDS)
            if not stopped and not self._resource_sampler.check_server_alive():
                self.logger.error("\n  ABORT: Server process is no longer running. Possible OOM kill.")
                server_dead_event.set()
                break
            self._resource_sampler.sample_client_rss()
            tick_count += 1
            line = self._progress_line(futures, total, start_seconds)
            self._progress_log_writer.write_to_file(line)
            self._progress_log_writer.write_to_console(tick_count, line, force=stopped)
            if stopped:
                break

    @staticmethod
    def format_duration_stats(durations: List[float]) -> str:
        """
        Format cumulative min/avg/max over durations.

        :param durations: Request durations in seconds
        :return: The min/avg/max text in whole minutes and seconds, e.g. "45s min / 1m 30s avg / 2m 5s max",
            or "n/a" when there are no durations yet
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
        min_text: str = DurationParser.format_minutes_seconds(min_seconds)
        average_text: str = DurationParser.format_minutes_seconds(average_seconds)
        max_text: str = DurationParser.format_minutes_seconds(max_seconds)
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
        system_memory_info: str = self._resource_sampler.system_memory_info()
        duration_info: str = self._duration_info(futures)
        system_cpu_info: str = self._resource_sampler.format_system_cpu()
        self._resource_sampler.sample_system_threads()
        duration_text: str = duration_info.strip()
        line: str = (f"  [progress] {progress_head}  {duration_text}{thread_info}{server_rss_info}"
                     f"{system_memory_info}{system_cpu_info}")
        return line

    def _progress_readings(self, futures: List[Future], total: int, start_seconds: float) -> Dict[str, str]:
        """
        Take the counts, times and server readings for the progress line.

        The server is sampled after the stall check and before the failed count is read.

        :param futures: Futures of the requests fired in this stage
        :param total: Number of requests in this stage
        :param start_seconds: perf_counter() value taken when the stage began
        :return: The dict from StageResourceSampler.sample_server_metrics(), plus "progress_head":
            "<done> of <total> completed (<percent>%) -- <elapsed> elapsed [<clock time>]",
            with the failed count inside the brackets and the stalled requests at the end when there are any
        """
        done_count: int = Heartbeat._count_done(futures)
        elapsed_seconds: int = int(perf_counter() - start_seconds)
        local_time: struct_time = localtime()
        timestamp: str = strftime("%H:%M:%S", local_time)
        percent_done: int = Heartbeat._percent(done_count, total)
        stall_info: str = self._stall_info(done_count, total)
        readings: Dict[str, str] = self._resource_sampler.sample_server_metrics()
        fail_info: str = self._fail_info(done_count)
        elapsed_text: str = DurationParser.format_minutes_seconds(elapsed_seconds)
        progress_head: str = (f"{done_count} of {total} completed ({percent_done}%{fail_info}) --"
                              f" {elapsed_text} elapsed [{timestamp}]{stall_info}")
        readings["progress_head"] = progress_head
        return readings

    def _stall_info(self, done_count: int, total: int) -> str:
        """
        Report the requests stalled since the done count last changed.

        :param done_count: Requests finished so far
        :param total: Number of requests in this stage
        :return: The stalled part of the progress line, or ""
        """
        stall_info: str = ""
        in_flight: int = total - done_count
        stall_seconds: Optional[int] = self._stall_tracker.stalled_seconds(done_count, total)
        if stall_seconds is not None:
            stall_text: str = DurationParser.format_minutes_seconds(stall_seconds)
            stall_info = f"  !! {in_flight} request(s) stalled for {stall_text}"
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

    def _duration_info(self, futures: List[Future]) -> str:
        """
        Format the client and server request durations for the progress line.

        :param futures: Futures of the requests fired in this stage
        :return: The dur/client part, and the dur/server part when the server log is read
        """
        client_durations: List[float] = Heartbeat._client_durations(futures)
        client_stats: str = Heartbeat.format_duration_stats(client_durations)
        duration_info: str = "  dur/client: " + client_stats
        server_durations: Optional[List[float]] = self._server_duration_reader.read_durations()
        if server_durations is not None:
            server_stats: str = Heartbeat.format_duration_stats(server_durations)
            duration_info += "  dur/server: " + server_stats
        return duration_info

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
            duration_seconds: Optional[float] = result.get("elapsed")
            if isinstance(duration_seconds, (int, float)) and duration_seconds > 0:
                duration_float: float = float(duration_seconds)
                durations.append(duration_float)
        return durations
