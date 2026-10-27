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
from logging import LoggerAdapter
from typing import Any
from typing import List

from leaf_common.logging.sensitive_logger import SensitiveLogger
from typing_extensions import override


class SensitiveErrorLogger(LoggerAdapter):
    """
    The logger of a class that logs caught errors. Each line goes to the wrapped logger as it is, except that a
    caught error passed as a %s value can hold sensitive data: when SensitiveLogger does not allow it
    (LEAF_LOG_SENSITIVE is "false"), the line shows only the error type, for example FileExistsError, so the
    operator still sees what failed. Each record still names the code that logged the line.
    Like SensitiveLogger, it reads LEAF_LOG_SENSITIVE once, when it is built.
    """

    def __init__(self, logger: Logger) -> None:
        """
        Constructor.

        :param logger: The logger to write each line to
        """
        super().__init__(logger)
        self.sensitive_logger: SensitiveLogger = SensitiveLogger(logger)

    # The signature matches LoggerAdapter.log(), which takes values and keyword arguments of any type, so the
    # *args varargs and the object and Any hints are forced here.
    @override
    def log(self, level: int, msg: object, *args: object, **kwargs: Any) -> None:
        """
        Log one line; when sensitive logging is off, each caught error in args shows as its type name.

        :param level: The logging level, such as DEBUG or WARNING
        :param msg: The %-format message
        :param args: The values for the %s of msg, in order
        :param kwargs: The keyword arguments of Logger.log(), such as exc_info or stacklevel
        """
        hide_errors: bool = not self.sensitive_logger.should_log()
        log_values: List[object] = []
        value: object
        # Keep each value; when hide_errors is set, a caught error becomes its type name.
        for value in args:
            # BaseException is the base class of every exception, so this checks the interface, not one concrete class.
            if hide_errors and isinstance(value, BaseException):
                error_type_name: str = type(value).__name__
                log_values.append(error_type_name)
            else:
                log_values.append(value)
        # One more stack level skips this method, so the record names the code that logged the line.
        stacklevel: int = kwargs.get("stacklevel", 1)
        kwargs["stacklevel"] = stacklevel + 1
        super().log(level, msg, *log_values, **kwargs)
