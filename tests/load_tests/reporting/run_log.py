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

import logging
import os
from logging import FileHandler
from logging import Formatter
from logging import Logger
from typing import Optional

from tests.load_tests.load_test_constants import LoadTestConstants


class RunLog:
    """
    Copies all log output of a load-test run to stdout.log in the run's output directory.

    The file handler goes on the root logger, so the file also gets the lines that other classes log.
    """

    def __init__(self) -> None:
        """
        Create a run log that is not open yet.
        """
        self._log_path: Optional[str] = None
        self._log_handler: Optional[FileHandler] = None

    def open(self, output_dir: str) -> None:
        """
        Start copying log output to stdout.log in the output directory.

        :param output_dir: The run's output directory, which must exist
        """
        self._log_path = os.path.join(output_dir, LoadTestConstants.STDOUT_LOG_FILE_NAME)
        self._log_handler = FileHandler(self._log_path, encoding="utf-8")
        self._log_handler.setLevel(logging.INFO)
        formatter: Formatter = Formatter("%(message)s")
        self._log_handler.setFormatter(formatter)
        root_logger: Logger = logging.getLogger()
        root_logger.addHandler(self._log_handler)

    def get_path(self) -> Optional[str]:
        """
        Return the path of stdout.log.

        :return: The stdout.log path, or None when the log was never opened
        """
        return self._log_path

    def close(self) -> None:
        """
        Stop copying log output and close stdout.log. Does nothing when the log was never opened.
        """
        if self._log_handler is None:
            return
        root_logger: Logger = logging.getLogger()
        root_logger.removeHandler(self._log_handler)
        self._log_handler.close()
