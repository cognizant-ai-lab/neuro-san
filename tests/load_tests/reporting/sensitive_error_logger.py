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

from logging import DEBUG
from logging import Logger
from logging import WARNING
from typing import List
from typing import Union

from leaf_common.logging.sensitive_logger import SensitiveLogger


class SensitiveErrorLogger:
    """
    Logs one line about a caught error. The error text can hold sensitive data, so it shows only when
    SensitiveLogger allows it (LEAF_LOG_SENSITIVE is not "false"). Otherwise the same line holds only the error
    type, for example FileExistsError, so the operator still sees what failed.
    Static methods: each caller passes its own logger, so the line keeps that logger's name and handlers.
    """

    @staticmethod
    def debug(logger: Logger, error: BaseException, message: str, message_values: List[str]) -> None:
        """
        Log a DEBUG line about a caught error.

        :param logger: The logger to write the line to
        :param error: The caught error; it fills the last %s of message
        :param message: The %-format message; its last %s is the error
        :param message_values: The values for the other %s of message, in order
        """
        SensitiveErrorLogger._log(DEBUG, logger, error, message, message_values)

    @staticmethod
    def warning(logger: Logger, error: BaseException, message: str, message_values: List[str]) -> None:
        """
        Log a WARNING line about a caught error.

        :param logger: The logger to write the line to
        :param error: The caught error; it fills the last %s of message
        :param message: The %-format message; its last %s is the error
        :param message_values: The values for the other %s of message, in order
        """
        SensitiveErrorLogger._log(WARNING, logger, error, message, message_values)

    @staticmethod
    def _log(level: int, logger: Logger, error: BaseException, message: str, message_values: List[str]) -> None:
        """
        Log the line with the error text, or with only the error type when sensitive logging is off.

        :param level: The logging level, such as DEBUG or WARNING
        :param logger: The logger to write the line to
        :param error: The caught error; it fills the last %s of message
        :param message: The %-format message; its last %s is the error
        :param message_values: The values for the other %s of message, in order
        """
        sensitive_logger: SensitiveLogger = SensitiveLogger(logger)
        error_text: Union[BaseException, str] = error
        if not sensitive_logger.should_log():
            error_text = type(error).__name__
        # stacklevel 3 makes the log record point at the code that called debug() or warning(), not at this class.
        logger.log(level, message, *message_values, error_text, stacklevel=3)
