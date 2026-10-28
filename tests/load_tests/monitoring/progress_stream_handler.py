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

from logging import StreamHandler


class ProgressStreamHandler(StreamHandler):
    """
    Writes ArrivalWatcher's arrival dots on one line of stdout.

    ArrivalWatcher logs one "." for each request the server receives. A plain StreamHandler ends every record with
    a newline, so each dot would print on its own line. This class only changes that ending (terminator) to "", so
    the dots print as "....." on one line, and ArrivalWatcher logs a "\n" when all requests have arrived.

    It is a class, not a setting in logging.hocon, because dictConfig has no plain key for the terminator: its "."
    key for setting handler attributes fails through the hocon loader ("Not a valid Python identifier").
    tests/load_tests/logging.hocon names this class for the "ArrivalWatcherProgress" logger.
    """

    # Written after each record: nothing, so the next dot follows on the same line.
    terminator: str = ""
