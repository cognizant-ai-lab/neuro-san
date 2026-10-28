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
    Stream handler that ends a record with no newline, so the arrival progress dots stay on one line.

    tests/load_tests/logging.hocon names this class for the "ArrivalWatcherProgress" logger. dictConfig cannot set
    the terminator from a hocon file, so the class holds it.
    """

    terminator: str = ""
