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

# Plain "import re": "from re import compile" would hide the builtin compile().
import re
from logging import Logger
from logging import getLogger
from os.path import join
from threading import Event
from threading import Thread
from time import localtime
from time import perf_counter
from time import strftime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import TextIO

from leaf_common.logging.sensitive_logger import SensitiveLogger
from psutil import Process

from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.reporting.duration_parser import DurationParser


class ArrivalWatcher:
    """
    Tails the server log on a background thread and reports each primary request arrival of a stage.

    The stage settings and the client process live on the instance, so the thread methods read them
    from self instead of passing them along. After start(), only the monitor thread uses the instance.
    """

    RECEIPT_FILE_NAME: str = "server_receipts.log"

    def __init__(self, arrival_settings: Dict[str, Any]) -> None:
        """
        Store the stage settings for the monitor thread.

        :param arrival_settings: A dict with the following keys:
            "expected_count"         Number of arrivals to wait for
            "fire_time_seconds"      perf_counter() value taken when the stage fired
            "stop_event"             Event that tells the monitor thread to stop
            "client_process"         Client Process for the snapshot once all requests arrive, or None
            "primary_start_pattern"  Regex for the log line of a primary agent request arriving
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        primary_start_pattern: str = arrival_settings.get("primary_start_pattern")
        self._expected_count: int = arrival_settings.get("expected_count")
        self._fire_time_seconds: float = arrival_settings.get("fire_time_seconds")
        self._stop_event: Event = arrival_settings.get("stop_event")
        self._client_process: Optional[Process] = arrival_settings.get("client_process")
        self._primary_start_regex: re.Pattern = re.compile(primary_start_pattern)
        # tests/load_tests/logging.hocon sends this logger to ProgressStreamHandler, so the dots stay on one line.
        self._progress_logger: Logger = getLogger(self.__class__.__name__ + "Progress")

    def start(self, server_log: str, position: int, output_dir: Optional[str] = None) -> Thread:
        """
        Start the background thread that tails the server log.

        :param server_log: Path of the server log
        :param position: Server log offset to start reading from
        :param output_dir: Directory for server_receipts.log, or None for console only
        :return: The started monitor thread
        """
        monitor: Thread = Thread(
            target=self._log_monitor_worker,
            args=[server_log, position, output_dir],
            daemon=True,
        )
        monitor.start()
        return monitor

    def _log_monitor_worker(self, server_log: str, position: int, output_dir: Optional[str]) -> None:
        """
        Background worker that tails server log and reports arrivals.

        :param server_log: Path of the server log
        :param position: Server log offset to start reading from
        :param output_dir: Directory for server_receipts.log, or None for console only
        """
        try:
            if output_dir:
                receipt_path: str = join(output_dir, ArrivalWatcher.RECEIPT_FILE_NAME)
                with open(receipt_path, "w", encoding="utf-8") as receipt_file:
                    self._read_server_log(server_log, position, receipt_file)
            else:
                self._read_server_log(server_log, position, None)
        except OSError as exc:
            sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)
            sensitive_logger.debug("Log monitor stopped: %s", exc)

    def _read_server_log(self, server_log: str, position: int, receipt_file: Optional[TextIO]) -> None:
        """
        Open the server log at the given position and tail it for arrivals.

        :param server_log: Path of the server log
        :param position: Server log offset to start reading from
        :param receipt_file: Open server_receipts.log, or None to log each receipt to the console
        """
        with open(server_log, "r", encoding="utf-8") as server_log_file:
            server_log_file.seek(position)
            self._tail_arrivals(server_log_file, receipt_file)

    def _tail_arrivals(self, server_log_file: TextIO, receipt_file: Optional[TextIO]) -> None:
        """
        Tail log for arrivals, printing dots or full lines.

        :param server_log_file: Open server log, positioned where to start reading
        :param receipt_file: Open server_receipts.log, or None to log each receipt to the console
        """
        # "Start hello_world/streaming_chat" gives the agent label "hello_world".
        pattern_head: str = self._primary_start_regex.pattern.split("/")[0]
        head_words: List[str] = pattern_head.split(" ")
        agent_label: str = head_words[-1]
        count: int = 0
        use_dots: bool = receipt_file is not None
        while not self._stop_event.is_set() and count < self._expected_count:
            line: str = server_log_file.readline()
            if not line:
                self._stop_event.wait(0.5)
                continue
            if not self._primary_start_regex.search(line):
                continue
            count += 1
            now_seconds: float = perf_counter()
            timestamp: str = strftime("%H:%M:%S", localtime())
            delta_seconds: float = now_seconds - self._fire_time_seconds
            delta_text: str = DurationParser.format_minutes_seconds(delta_seconds)
            detail: str = (f"  [server] {agent_label} request {count}/{self._expected_count} received"
                           f" [{timestamp}] (+{delta_text})")
            if use_dots:
                receipt_file.write(detail + "\n")
                receipt_file.flush()
                self._progress_logger.info(".")
            else:
                self.logger.info("%s", detail)
            if count >= self._expected_count:
                self._log_all_received(use_dots, count, delta_seconds)

    def _log_all_received(self, use_dots: bool, count: int, elapsed_seconds: float) -> None:
        """
        Log the final receipt summary and client snapshot.

        :param use_dots: True when arrivals were shown as dots, so the dot line needs ending
        :param count: Number of arrivals seen
        :param elapsed_seconds: Seconds from firing to the last arrival
        """
        if use_dots:
            self._progress_logger.info("\n")
            elapsed_text: str = DurationParser.format_minutes_seconds(elapsed_seconds)
            self.logger.info("  All %s/%s requests received by server (%s)", count, self._expected_count,
                             elapsed_text)
        snapshot: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(self._client_process)
        if snapshot:
            client_rss_megabytes: float = snapshot.get("rss_megabytes")
            client_cpu_percent: float = snapshot.get("cpu_percent")
            self.logger.info("  Client AFTER: RSS %.1f MB, CPU %.1f%%", client_rss_megabytes,
                             client_cpu_percent)
        ResourceMonitor.log_system_memory("RECEIVED")
