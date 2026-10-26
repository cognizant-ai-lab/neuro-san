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
from logging import INFO
from logging import Logger
from logging import getLogger
from os.path import join
from tempfile import TemporaryDirectory
from typing import Optional
from unittest import TestCase

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.reporting.run_log import RunLog


class TestRunLog(TestCase):
    """
    Tests for RunLog: copying log output to stdout.log in the run's output directory.
    """

    def test_open_copies_root_log_lines_until_close(self) -> None:
        """
        Root logger INFO lines go to stdout.log while the run log is open, and not after close().
        """
        with TemporaryDirectory() as output_dir:
            run_log: RunLog = RunLog()
            run_log.open(output_dir)
            root_logger: Logger = getLogger()
            previous_level: int = root_logger.level
            root_logger.setLevel(INFO)
            try:
                root_logger.info("line while open")
                run_log.close()
                root_logger.info("line after close")
            finally:
                root_logger.setLevel(previous_level)
            log_path: Optional[str] = run_log.get_path()
            expected_log_path: str = join(output_dir, LoadTestConstants.STDOUT_LOG_FILE_NAME)
            self.assertEqual(log_path, expected_log_path)
            with open(log_path, "r", encoding="utf-8") as log_file:
                log_text: str = log_file.read()
            self.assertEqual(log_text, "line while open\n")

    def test_close_without_open(self) -> None:
        """
        close() on a run log that was never opened does nothing, and get_path() is None.
        """
        run_log: RunLog = RunLog()
        run_log.close()
        self.assertIsNone(run_log.get_path())
