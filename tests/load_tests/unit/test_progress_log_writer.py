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
from os.path import exists
from os.path import join
from tempfile import TemporaryDirectory
from unittest import TestCase

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.progress_log_writer import ProgressLogWriter


class TestProgressLogWriter(TestCase):
    """
    Unit tests for ProgressLogWriter: its progress.log lines and its console lines.
    """

    def test_write_to_file_appends_lines(self) -> None:
        """
        Each line is appended to progress.log, after what is already there.
        """
        progress_text: str = ""
        with TemporaryDirectory() as output_dir:
            writer: ProgressLogWriter = ProgressLogWriter(output_dir)
            writer.write_to_file("first")
            writer.write_to_file("second")
            progress_log_path: str = join(output_dir, LoadTestConstants.PROGRESS_LOG_FILE_NAME)
            with open(progress_log_path, encoding="utf-8") as progress_log:
                progress_text = progress_log.read()
        self.assertEqual("first\nsecond\n", progress_text)

    def test_write_to_file_without_output_dir_writes_nothing(self) -> None:
        """
        With no output directory, no progress.log is created.
        """
        with TemporaryDirectory() as output_dir:
            writer: ProgressLogWriter = ProgressLogWriter(None)
            writer.write_to_file("line")
            progress_log_path: str = join(output_dir, LoadTestConstants.PROGRESS_LOG_FILE_NAME)
            progress_log_written: bool = exists(progress_log_path)
            self.assertFalse(progress_log_written)

    def test_write_to_console_logs_the_line(self) -> None:
        """
        The progress line is logged at INFO.
        """
        writer: ProgressLogWriter = ProgressLogWriter(None)
        with self.assertLogs("ProgressLogWriter", level="INFO") as captured:
            writer.write_to_console(1, "  [progress] 1 of 1 completed")
        self.assertIn("  [progress] 1 of 1 completed", captured.output[0])
