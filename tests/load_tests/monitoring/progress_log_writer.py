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

# Whole sys module: sys.stdout is looked up on each write, so a swapped stdout is used.
import sys
from logging import Logger
from logging import getLogger
from os.path import join
from typing import Optional

from tests.load_tests.load_test_constants import LoadTestConstants


class ProgressLogWriter:
    """
    Writes the heartbeat's progress lines and resource warnings to progress.log and to the console.

    Heartbeat and StageResourceSampler share one writer per stage, so the blank line before the first console
    line is written only once.
    """

    # Write a console progress line every this many heartbeat ticks.
    CONSOLE_INTERVAL_TICKS: int = 1

    def __init__(self, output_dir: Optional[str]) -> None:
        """
        Constructor.

        :param output_dir: Directory for progress.log, or None for console only
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self._output_dir: Optional[str] = output_dir
        self._console_started: bool = False

    def write_to_file(self, line: str, end: str = "\n") -> None:
        """
        Append a line to progress.log, when output_dir is set.

        The file is opened for each line in append mode, so the request lines TrafficRunner writes there stay.

        :param line: The line to write
        :param end: Text written after the line. Heartbeat.progress_heartbeat() writes "" with end "" to create the file
            before the first tick, so a stage with no tick still leaves an empty progress.log.
        """
        if not self._output_dir:
            return
        path: str = join(self._output_dir, LoadTestConstants.PROGRESS_LOG_FILE_NAME)
        file_line: str = line + end
        with open(path, "a", encoding="utf-8") as progress_file:
            progress_file.write(file_line)

    def write_to_console(self, tick_count: int, line: str, force: bool = False) -> None:
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
                or tick_count % ProgressLogWriter.CONSOLE_INTERVAL_TICKS == 0):
            if not self._console_started:
                sys.stdout.write("\n")
                self._console_started = True
            self.logger.info("%s", line)
