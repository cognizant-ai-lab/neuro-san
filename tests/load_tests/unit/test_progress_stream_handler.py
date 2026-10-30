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

from io import StringIO
from logging import INFO
from logging import LogRecord
from unittest import TestCase

from tests.load_tests.monitoring.progress_stream_handler import ProgressStreamHandler


class TestProgressStreamHandler(TestCase):
    """
    Unit tests for ProgressStreamHandler, the handler logging.hocon names for the arrival progress dots.
    """

    def test_records_are_written_with_no_newline(self) -> None:
        """
        Two dots logged one after the other stay on one line.
        """
        stream: StringIO = StringIO()
        handler: ProgressStreamHandler = ProgressStreamHandler(stream)
        dot_record: LogRecord = LogRecord("ArrivalWatcherProgress", INFO, __file__, 1, ".", None, None)
        handler.emit(dot_record)
        handler.emit(dot_record)
        written_text: str = stream.getvalue()
        self.assertEqual("..", written_text)
