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

from logging import Logger
from logging import getLogger
from os import environ
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.reporting.sensitive_error_logger import SensitiveErrorLogger


class TestSensitiveErrorLogger(TestCase):
    """
    Tests for SensitiveErrorLogger: a caught error shows as text only when sensitive logging is on, other values
    stay as they are, and each record names the code that logged it.
    """

    LOGGER_NAME: str = "tests.load_tests.unit.test_sensitive_error_logger"

    def test_warning_logs_the_error(self) -> None:
        """
        With LEAF_LOG_SENSITIVE=true the warning holds the other values and the error text.
        """
        logger: Logger = getLogger(TestSensitiveErrorLogger.LOGGER_NAME)
        error: OSError = OSError("disk full")
        with patch.dict(environ, {"LEAF_LOG_SENSITIVE": "true"}), \
                self.assertLogs(TestSensitiveErrorLogger.LOGGER_NAME, level="WARNING") as captured:
            error_logger: SensitiveErrorLogger = SensitiveErrorLogger(logger)
            error_logger.warning("Could not write %s: %s", "out.txt", error)
        expected_line: str = f"WARNING:{TestSensitiveErrorLogger.LOGGER_NAME}:Could not write out.txt: disk full"
        self.assertEqual(captured.output, [expected_line])

    def test_warning_logs_only_the_error_type_when_sensitive_logging_is_off(self) -> None:
        """
        With LEAF_LOG_SENSITIVE=false the warning holds the other values and only the error type.
        """
        logger: Logger = getLogger(TestSensitiveErrorLogger.LOGGER_NAME)
        error: OSError = OSError("disk full")
        with patch.dict(environ, {"LEAF_LOG_SENSITIVE": "false"}), \
                self.assertLogs(TestSensitiveErrorLogger.LOGGER_NAME, level="WARNING") as captured:
            error_logger: SensitiveErrorLogger = SensitiveErrorLogger(logger)
            error_logger.warning("Could not write %s: %s", "out.txt", error)
        expected_line: str = f"WARNING:{TestSensitiveErrorLogger.LOGGER_NAME}:Could not write out.txt: OSError"
        self.assertEqual(captured.output, [expected_line])

    def test_debug_logs_the_error(self) -> None:
        """
        With LEAF_LOG_SENSITIVE=true the debug line holds the error text.
        """
        logger: Logger = getLogger(TestSensitiveErrorLogger.LOGGER_NAME)
        error: ValueError = ValueError("no such process")
        with patch.dict(environ, {"LEAF_LOG_SENSITIVE": "true"}), \
                self.assertLogs(TestSensitiveErrorLogger.LOGGER_NAME, level="DEBUG") as captured:
            error_logger: SensitiveErrorLogger = SensitiveErrorLogger(logger)
            error_logger.debug("Thread count unavailable: %s", error)
        expected_line: str = f"DEBUG:{TestSensitiveErrorLogger.LOGGER_NAME}:Thread count unavailable: no such process"
        self.assertEqual(captured.output, [expected_line])

    def test_debug_logs_only_the_error_type_when_sensitive_logging_is_off(self) -> None:
        """
        With LEAF_LOG_SENSITIVE=false the debug line holds only the error type.
        """
        logger: Logger = getLogger(TestSensitiveErrorLogger.LOGGER_NAME)
        error: ValueError = ValueError("no such process")
        with patch.dict(environ, {"LEAF_LOG_SENSITIVE": "false"}), \
                self.assertLogs(TestSensitiveErrorLogger.LOGGER_NAME, level="DEBUG") as captured:
            error_logger: SensitiveErrorLogger = SensitiveErrorLogger(logger)
            error_logger.debug("Thread count unavailable: %s", error)
        expected_line: str = f"DEBUG:{TestSensitiveErrorLogger.LOGGER_NAME}:Thread count unavailable: ValueError"
        self.assertEqual(captured.output, [expected_line])

    def test_values_that_are_not_errors_stay_when_sensitive_logging_is_off(self) -> None:
        """
        With LEAF_LOG_SENSITIVE=false a line without a caught error is logged as it is.
        """
        logger: Logger = getLogger(TestSensitiveErrorLogger.LOGGER_NAME)
        with patch.dict(environ, {"LEAF_LOG_SENSITIVE": "false"}), \
                self.assertLogs(TestSensitiveErrorLogger.LOGGER_NAME, level="INFO") as captured:
            error_logger: SensitiveErrorLogger = SensitiveErrorLogger(logger)
            error_logger.info("Wrote %s rows to %s", 3, "out.txt")
        expected_line: str = f"INFO:{TestSensitiveErrorLogger.LOGGER_NAME}:Wrote 3 rows to out.txt"
        self.assertEqual(captured.output, [expected_line])

    def test_log_record_points_at_the_caller(self) -> None:
        """
        The log record names the method that logged the line, not a SensitiveErrorLogger method.
        """
        logger: Logger = getLogger(TestSensitiveErrorLogger.LOGGER_NAME)
        error: OSError = OSError("disk full")
        with self.assertLogs(TestSensitiveErrorLogger.LOGGER_NAME, level="WARNING") as captured:
            error_logger: SensitiveErrorLogger = SensitiveErrorLogger(logger)
            error_logger.warning("Could not write: %s", error)
        self.assertEqual(captured.records[0].funcName, "test_log_record_points_at_the_caller")
