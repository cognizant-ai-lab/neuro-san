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

from argparse import Namespace
from logging import Logger
from logging import getLogger
from re import Pattern
from time import localtime
from time import perf_counter
from time import sleep
from time import strftime
from time import struct_time
from time import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import TextIO

from psutil import Process
from psutil import cpu_percent
from psutil import virtual_memory

from tests.load_tests.duration import DurationParser
from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.reporting.system_resources import SystemResources


class ServerLogTailer:
    """
    Follows the server log during a server-only round: counts the primary agent's Start and Finish lines,
    tracks peak server and system resources, and logs a heartbeat.
    """

    POLL_SECONDS: float = 0.5
    MONITOR_INTERVAL_SECONDS: float = 1.0
    LOG_LIMIT_REQUESTS: int = 5

    def __init__(self, args: Namespace, server_process: Optional[Process],
                 log_monitor: Optional[ServerLogMonitor]) -> None:
        """
        Store what the tailer reads.

        :param args: Parsed command-line arguments, with "server_log" and "stage_timeout"
        :param server_process: The local server process, or None when it is not found
        :param log_monitor: Monitor of the server log, or None when there is no server log
        """
        self.args: Namespace = args
        self.server_log: Optional[str] = args.server_log
        self.server_process: Optional[Process] = server_process
        self.log_monitor: Optional[ServerLogMonitor] = log_monitor
        self.logger: Logger = getLogger(self.__class__.__name__)

    def tail_server_log(self, round_values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Tail the server log in two phases.

        Phase 1 counts Start patterns until all requests are received. Phase 2 counts Finish patterns until all
        requests are processed.

        :param round_values: A dict with "expected" (number of requests to wait for), "log_position" (server log
            offset to start reading from), "primary_start_regex" and "primary_finish_regex" (the primary agent's
            Start and Finish log lines), "before_server" (server snapshot before the round, or None) and
            "before_system_memory_percent" (system memory use in percent before the round)
        :return: Dict with "count" (requests received), "completed" (requests processed), "peak_server" (peak server
            snapshot), "peak_threads", "peak_sys_mem_pct", "elapsed_seconds", "interrupted" (True on Ctrl-C),
            "peak_sys_cpu_percent", "avg_sys_cpu_percent" and "peak_sys_threads"
        """
        tail_state: Dict[str, Any] = ServerLogTailer._new_tail_state(round_values)
        log_position: Optional[int] = round_values.get("log_position")
        finished: bool = False
        # Prime the non-blocking system CPU counter.
        cpu_percent(interval=None)
        try:
            with open(self.server_log, "r", encoding="utf-8") as server_log_file:
                server_log_file.seek(log_position)
                # Read or wait for one log line per pass until the round finishes or times out.
                while not finished:
                    finished = self._tail_step(server_log_file, round_values, tail_state)
        except KeyboardInterrupt:
            tail_state["interrupted"] = True
            # The em dash "—" matches the other interrupt messages; plain "-" would change the output.
            self.logger.info("\n  Interrupted — reporting partial results...")
        tail_result: Dict[str, Any] = ServerLogTailer._tail_result(tail_state)
        return tail_result

    def snapshot_server(self) -> Optional[Dict[str, Any]]:
        """
        Take a resource snapshot of the local server process.

        :return: The snapshot, or None when there is no server process
        """
        server_snapshot: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(self.server_process)
        return server_snapshot

    def server_only_primary_pairs(self, log_position: Optional[int],
                                  primary_start_regex: Pattern) -> List[Dict[str, Any]]:
        """
        Primary-agent streaming_chat Start/Finish pairs since log_position.

        :param log_position: Server log position at the start of the round
        :param primary_start_regex: Compiled pattern for the primary agent's Start line
        :return: The pairs of the primary (front-man) agent, each with "agent", "start_ts", "finish_ts",
                 "duration_seconds" and "request_id"; empty when there is no log monitor, on a read error,
                 or before a primary request completes
        """
        if self.log_monitor is None:
            return []
        pairs: List[Dict[str, Any]] = []
        try:
            pairs = self.log_monitor.parse_streaming_chat_timing_since(log_position)
        except (OSError, ValueError):
            return []
        primary: List[Dict[str, Any]] = []
        agent: str = ""
        start_line: str = ""
        pair: Dict[str, Any]
        # Keep the pairs of the primary agent.
        for pair in pairs:
            agent = pair.get("agent", "")
            start_line = f"Start {agent}/streaming_chat"
            if primary_start_regex.search(start_line):
                primary.append(pair)
        return primary

    @staticmethod
    def positive_durations(pairs: List[Dict[str, Any]]) -> List[float]:
        """
        Read the durations of the Start/Finish pairs whose duration is a number above 0.

        :param pairs: Start/Finish pairs, each with "duration_seconds"
        :return: The durations in seconds, in pair order
        """
        durations: List[float] = []
        duration_seconds: Optional[float] = None
        pair: Dict[str, Any]
        # Keep each pair whose duration is a number above 0.
        for pair in pairs:
            duration_seconds = pair.get("duration_seconds")
            if isinstance(duration_seconds, (int, float)):
                number_seconds: float = float(duration_seconds)
                if number_seconds > 0:
                    durations.append(number_seconds)
        return durations

    def _server_only_duration_stats(self, log_position: Optional[int], primary_start_regex: Pattern) -> str:
        """
        Cumulative server-side min/avg/max for the primary agent.

        Parses primary streaming_chat Start/Finish pairs seen since
        the round's log position and formats them.

        :param log_position: Server log position at the start of the round
        :param primary_start_regex: Compiled pattern for the primary agent's Start line
        :return: The formatted stats, or "n/a" until at least one request has completed
        """
        primary_pairs: List[Dict[str, Any]] = self.server_only_primary_pairs(log_position, primary_start_regex)
        durations: List[float] = ServerLogTailer.positive_durations(primary_pairs)
        duration_stats_text: str = Heartbeat.format_duration_stats(durations)
        return duration_stats_text

    def _server_only_heartbeat(self, heartbeat_values: Dict[str, Any]) -> None:
        """
        Log a periodic heartbeat during server-only monitoring.

        :param heartbeat_values: A dict with "received", "expected", "completed",
                                 "elapsed_seconds", "now_seconds" (wall clock), "server_snapshot",
                                 "virtual_memory_stats" (the psutil.virtual_memory() result), "duration_stats",
                                 "current_system_cpu_percent" and "peak_system_cpu_percent"
        """
        elapsed_seconds: float = heartbeat_values.get("elapsed_seconds")
        now_seconds: float = heartbeat_values.get("now_seconds")
        duration_stats: str = heartbeat_values.get("duration_stats", "n/a")
        server_snapshot: Optional[Dict[str, Any]] = heartbeat_values.get("server_snapshot")
        server_text: str = ServerLogTailer._server_text(server_snapshot)
        # psutil.virtual_memory() returns psutil's private svmem named tuple, which has no public type to name.
        virtual_memory_stats: Any = heartbeat_values.get("virtual_memory_stats")
        system_memory_text: str = ResourceMonitor.system_memory_text(virtual_memory_stats)
        local_time: struct_time = localtime(now_seconds)
        timestamp: str = strftime("%H:%M:%S", local_time)
        elapsed_whole_seconds: int = int(elapsed_seconds)
        elapsed_text: str = DurationParser.format_minutes_seconds(elapsed_whole_seconds)
        progress_text: str = ServerLogTailer._progress_text(heartbeat_values)
        system_cpu_text: str = ServerLogTailer._system_cpu_text(heartbeat_values)
        self.logger.info(
            "  [heartbeat] %s [%s]%s  dur/server: %s%s%s%s",
            elapsed_text, timestamp,
            progress_text,
            duration_stats,
            server_text,
            system_memory_text,
            system_cpu_text,
        )

    @staticmethod
    def _server_text(server_snapshot: Optional[Dict[str, Any]]) -> str:
        """
        Format the server threads and RSS part of the heartbeat.

        :param server_snapshot: Server snapshot, or None when there is no server process
        :return: "  threads: N  RSS: N MB", or "" without a snapshot
        """
        server_text: str = ""
        server_rss_megabytes: float = 0.0
        server_threads: int = 0
        if server_snapshot:
            server_rss_megabytes = server_snapshot.get("rss_megabytes", 0)
            server_threads = server_snapshot.get("threads", 0)
            server_text = f"  threads: {server_threads}  RSS: {server_rss_megabytes:.0f} MB"
        return server_text

    @staticmethod
    def _progress_text(heartbeat_values: Dict[str, Any]) -> str:
        """
        Format the request progress part of the heartbeat.

        :param heartbeat_values: The heartbeat values, with "received", "expected" and "completed"
        :return: The received, done and in-flight counts
        """
        received: int = heartbeat_values.get("received")
        expected_count: int = heartbeat_values.get("expected")
        completed: int = heartbeat_values.get("completed")
        in_flight: int = max(0, received - completed)
        progress_text: str = f" {received}/{expected_count} recv  {completed} done  {in_flight} in-flight"
        if received >= expected_count:
            progress_text = f" {expected_count} recv  {completed}/{expected_count} done  {in_flight} in-flight"
        return progress_text

    @staticmethod
    def _system_cpu_text(heartbeat_values: Dict[str, Any]) -> str:
        """
        Format the system CPU part of the heartbeat.

        :param heartbeat_values: The heartbeat values, with "current_system_cpu_percent" (None before the first
            sample) and "peak_system_cpu_percent"
        :return: "  syscpu: N% (peak N%)", or "" before the first sample
        """
        current_system_cpu_percent: Optional[float] = heartbeat_values.get("current_system_cpu_percent")
        peak_system_cpu_percent: Optional[float] = heartbeat_values.get("peak_system_cpu_percent")
        system_cpu_text: str = ""
        shown_peak_cpu_percent: float = 0.0
        if current_system_cpu_percent is not None:
            shown_peak_cpu_percent = current_system_cpu_percent
            if peak_system_cpu_percent is not None:
                shown_peak_cpu_percent = peak_system_cpu_percent
            system_cpu_text = f"  syscpu: {current_system_cpu_percent:.0f}% (peak {shown_peak_cpu_percent:.0f}%)"
        return system_cpu_text

    @staticmethod
    def _new_tail_state(round_values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make the counters and peaks that one tail of the server log updates.

        :param round_values: The round values passed to tail_server_log()
        :return: Dict of the round's counters, peaks and perf_counter() times in seconds
        """
        start_seconds: float = perf_counter()
        tail_state: Dict[str, Any] = {
            "start_seconds": start_seconds,
            "last_heartbeat_seconds": start_seconds,
            "last_monitor_seconds": start_seconds,
            "received_count": 0,
            "completed_count": 0,
            "phase": 1,
            "peak_server": round_values.get("before_server"),
            "peak_threads": 0,
            "peak_system_memory_percent": round_values.get("before_system_memory_percent"),
            "peak_system_cpu_percent": 0.0,
            "peak_system_threads": 0,
            "system_cpu_percent_sum": 0.0,
            "system_cpu_samples": 0,
            "interrupted": False,
            "warned_missing_starts": False,
        }
        return tail_state

    def _tail_step(self, server_log_file: TextIO, round_values: Dict[str, Any], tail_state: Dict[str, Any]) -> bool:
        """
        Read one line of the server log, or wait for one and sample resources.

        :param server_log_file: The open server log
        :param round_values: The round values passed to tail_server_log()
        :param tail_state: The round's counters and peaks; updated here
        :return: True when the round is finished or the stage timeout is reached
        """
        if self._round_finished(round_values, tail_state):
            return True
        line: str = server_log_file.readline()
        if line:
            self._count_log_line(line, round_values, tail_state)
            return False
        position: int = server_log_file.tell()
        server_log_file.seek(position)
        sleep(ServerLogTailer.POLL_SECONDS)
        now_perf_seconds: float = perf_counter()
        elapsed_seconds: float = now_perf_seconds - tail_state.get("start_seconds")
        last_monitor_seconds: float = tail_state.get("last_monitor_seconds")
        if now_perf_seconds - last_monitor_seconds >= ServerLogTailer.MONITOR_INTERVAL_SECONDS:
            self._sample_resources(tail_state)
            tail_state["last_monitor_seconds"] = now_perf_seconds
            self._maybe_heartbeat(round_values, tail_state, now_perf_seconds, elapsed_seconds)
        timed_out: bool = self._stage_timed_out(round_values, tail_state, elapsed_seconds)
        return timed_out

    def _round_finished(self, round_values: Dict[str, Any], tail_state: Dict[str, Any]) -> bool:
        """
        Move to phase 2 once every request is received, and say when the round is finished.

        :param round_values: The round values passed to tail_server_log()
        :param tail_state: The round's counters and peaks; "phase" and "warned_missing_starts" are updated here
        :return: True when every received request is processed, or more completions than starts reach expected
        """
        expected_count: int = round_values.get("expected")
        received_count: int = tail_state.get("received_count")
        completed_count: int = tail_state.get("completed_count")
        phase: int = tail_state.get("phase")
        elapsed_seconds: float = 0.0
        if phase == 1 and received_count >= expected_count:
            elapsed_seconds = ServerLogTailer._elapsed_seconds(tail_state)
            all_received_text: str = DurationParser.format_minutes_seconds(elapsed_seconds)
            self.logger.info(
                "\n  All %d request(s) received (%s). Monitoring until processing completes...",
                expected_count, all_received_text,
            )
            phase = 2
            tail_state["phase"] = phase
        if phase == 2 and completed_count >= received_count:
            return True
        # Guard: completions arriving without matching starts means the monitor was started after the client
        # fired, so the Start lines predate our read position and were skipped. Warn and finish gracefully
        # instead of hanging with negative in-flight.
        if completed_count > received_count:
            if not tail_state.get("warned_missing_starts"):
                self.logger.warning(
                    "\n  %d completion(s) seen with only %d start(s). The server-only monitor was likely started "
                    "after the client; Start lines predate its read position and were missed. Received counts are "
                    "unreliable -- start the monitor before the client.",
                    completed_count, received_count,
                )
                tail_state["warned_missing_starts"] = True
            if completed_count >= expected_count:
                return True
        return False

    def _count_log_line(self, line: str, round_values: Dict[str, Any], tail_state: Dict[str, Any]) -> None:
        """
        Count a Start line in phase 1 and a Finish line in both phases, and log the first few and the last one.

        :param line: One line of the server log
        :param round_values: The round values passed to tail_server_log()
        :param tail_state: The round's counters and peaks; "received_count" and "completed_count" are updated here
        """
        expected_count: int = round_values.get("expected")
        primary_start_regex: Pattern = round_values.get("primary_start_regex")
        primary_finish_regex: Pattern = round_values.get("primary_finish_regex")
        phase: int = tail_state.get("phase")
        received_count: int = tail_state.get("received_count")
        completed_count: int = tail_state.get("completed_count")
        timestamp: str = ""
        elapsed_seconds: float = 0.0
        total_requests: int = 0
        if phase == 1 and primary_start_regex.search(line):
            received_count += 1
            tail_state["received_count"] = received_count
            timestamp = ServerLogTailer._timestamp_now()
            elapsed_seconds = ServerLogTailer._elapsed_seconds(tail_state)
            if received_count <= ServerLogTailer.LOG_LIMIT_REQUESTS or received_count == expected_count:
                received_text: str = DurationParser.format_minutes_seconds(elapsed_seconds)
                self.logger.info(
                    "  [server] request %d/%d received [%s] (+%s)",
                    received_count, expected_count,
                    timestamp, received_text,
                )
        if primary_finish_regex.search(line):
            completed_count += 1
            tail_state["completed_count"] = completed_count
            timestamp = ServerLogTailer._timestamp_now()
            elapsed_seconds = ServerLogTailer._elapsed_seconds(tail_state)
            total_requests = expected_count
            if phase == 2:
                total_requests = received_count
            if completed_count <= ServerLogTailer.LOG_LIMIT_REQUESTS or completed_count == total_requests:
                completed_text: str = DurationParser.format_minutes_seconds(elapsed_seconds)
                self.logger.info(
                    "  [server] request %d/%d completed [%s] (+%s)",
                    completed_count, total_requests,
                    timestamp, completed_text,
                )

    def _sample_resources(self, tail_state: Dict[str, Any]) -> None:
        """
        Sample the server and system resources and keep the peaks.

        :param tail_state: The round's counters and peaks; the peaks, CPU sums and the "last_*" samples are
            updated here
        """
        peak_server: Optional[Dict[str, Any]] = tail_state.get("peak_server")
        server_snapshot: Optional[Dict[str, Any]] = self.snapshot_server()
        server_rss_megabytes: float = 0.0
        current_threads: int = 0
        peak_threads: int = tail_state.get("peak_threads")
        if server_snapshot:
            server_rss_megabytes = server_snapshot.get("rss_megabytes", 0)
            if peak_server is None or server_rss_megabytes > peak_server.get("rss_megabytes", 0):
                tail_state["peak_server"] = server_snapshot
            current_threads = server_snapshot.get("threads", 0)
            tail_state["peak_threads"] = max(peak_threads, current_threads)
        # psutil.virtual_memory() returns psutil's private svmem named tuple, which has no public type to name.
        virtual_memory_stats: Any = virtual_memory()
        peak_system_memory_percent: float = tail_state.get("peak_system_memory_percent")
        tail_state["peak_system_memory_percent"] = max(peak_system_memory_percent, virtual_memory_stats.percent)
        current_system_cpu_percent: float = cpu_percent(interval=None)
        system_cpu_percent_sum: float = tail_state.get("system_cpu_percent_sum")
        system_cpu_samples: int = tail_state.get("system_cpu_samples")
        tail_state["system_cpu_percent_sum"] = system_cpu_percent_sum + current_system_cpu_percent
        tail_state["system_cpu_samples"] = system_cpu_samples + 1
        peak_system_cpu_percent: float = tail_state.get("peak_system_cpu_percent")
        tail_state["peak_system_cpu_percent"] = max(peak_system_cpu_percent, current_system_cpu_percent)
        total_threads: int = SystemResources.total_threads()
        peak_system_threads: int = tail_state.get("peak_system_threads")
        tail_state["peak_system_threads"] = max(peak_system_threads, total_threads)
        tail_state["last_server_snapshot"] = server_snapshot
        tail_state["last_virtual_memory_stats"] = virtual_memory_stats
        tail_state["last_system_cpu_percent"] = current_system_cpu_percent

    def _maybe_heartbeat(self, round_values: Dict[str, Any], tail_state: Dict[str, Any], now_perf_seconds: float,
                         elapsed_seconds: float) -> None:
        """
        Log a heartbeat when LoadTestConstants.HEARTBEAT_INTERVAL_SECONDS have passed since the last one.

        :param round_values: The round values passed to tail_server_log()
        :param tail_state: The round's counters and peaks; "last_heartbeat_seconds" is updated here
        :param now_perf_seconds: time.perf_counter() now
        :param elapsed_seconds: Seconds since the tail started
        """
        last_heartbeat_seconds: float = tail_state.get("last_heartbeat_seconds")
        if now_perf_seconds - last_heartbeat_seconds < LoadTestConstants.HEARTBEAT_INTERVAL_SECONDS:
            return
        log_position: Optional[int] = round_values.get("log_position")
        primary_start_regex: Pattern = round_values.get("primary_start_regex")
        duration_stats: str = self._server_only_duration_stats(log_position, primary_start_regex)
        now_seconds: float = time()
        heartbeat_values: Dict[str, Any] = {
            "received": tail_state.get("received_count"),
            "expected": round_values.get("expected"),
            "completed": tail_state.get("completed_count"),
            "elapsed_seconds": elapsed_seconds,
            "now_seconds": now_seconds,
            "server_snapshot": tail_state.get("last_server_snapshot"),
            "virtual_memory_stats": tail_state.get("last_virtual_memory_stats"),
            "duration_stats": duration_stats,
            "current_system_cpu_percent": tail_state.get("last_system_cpu_percent"),
            "peak_system_cpu_percent": tail_state.get("peak_system_cpu_percent"),
        }
        self._server_only_heartbeat(heartbeat_values)
        tail_state["last_heartbeat_seconds"] = now_perf_seconds

    def _stage_timed_out(self, round_values: Dict[str, Any], tail_state: Dict[str, Any],
                         elapsed_seconds: float) -> bool:
        """
        Warn and say so when the round has run longer than --stage-timeout.

        :param round_values: The round values passed to tail_server_log()
        :param tail_state: The round's counters and peaks
        :param elapsed_seconds: Seconds since the tail started
        :return: True when the stage timeout is reached
        """
        if elapsed_seconds <= self.args.stage_timeout:
            return False
        expected_count: int = round_values.get("expected")
        received_count: int = tail_state.get("received_count")
        completed_count: int = tail_state.get("completed_count")
        if tail_state.get("phase") == 1:
            self.logger.warning(
                "  Stage timeout (%.0fs) reached with %d/%d requests received.",
                self.args.stage_timeout,
                received_count, expected_count,
            )
        else:
            self.logger.warning(
                "  Stage timeout (%.0fs) reached with %d/%d requests processed.",
                self.args.stage_timeout,
                completed_count, received_count,
            )
        return True

    @staticmethod
    def _elapsed_seconds(tail_state: Dict[str, Any]) -> float:
        """
        Seconds since the tail started, from time.perf_counter().

        :param tail_state: The round's counters and peaks, with "start_seconds"
        :return: Seconds since the tail started
        """
        now_perf_seconds: float = perf_counter()
        elapsed_seconds: float = now_perf_seconds - tail_state.get("start_seconds")
        return elapsed_seconds

    @staticmethod
    def _timestamp_now() -> str:
        """
        The wall-clock time now, for the printed timestamps.

        :return: The local time as HH:MM:SS
        """
        now_seconds: float = time()
        local_time: struct_time = localtime(now_seconds)
        timestamp: str = strftime("%H:%M:%S", local_time)
        return timestamp

    @staticmethod
    def _tail_result(tail_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build the tail result from the round's counters and peaks.

        :param tail_state: The round's counters and peaks
        :return: The dict tail_server_log() returns
        """
        elapsed_seconds: float = ServerLogTailer._elapsed_seconds(tail_state)
        system_cpu_samples: int = tail_state.get("system_cpu_samples")
        avg_system_cpu_percent: float = 0.0
        if system_cpu_samples:
            avg_system_cpu_percent = tail_state.get("system_cpu_percent_sum") / system_cpu_samples
        tail_result: Dict[str, Any] = {
            "count": tail_state.get("received_count"),
            "completed": tail_state.get("completed_count"),
            "peak_server": tail_state.get("peak_server"),
            "peak_threads": tail_state.get("peak_threads"),
            "peak_sys_mem_pct": tail_state.get("peak_system_memory_percent"),
            "elapsed_seconds": elapsed_seconds,
            "interrupted": tail_state.get("interrupted"),
            "peak_sys_cpu_percent": tail_state.get("peak_system_cpu_percent"),
            "avg_sys_cpu_percent": avg_system_cpu_percent,
            "peak_sys_threads": tail_state.get("peak_system_threads"),
        }
        return tail_result
