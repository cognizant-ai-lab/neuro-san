
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

from typing import Optional

from neuro_san.test.interfaces.assert_forwarder import AssertForwarder
from neuro_san.test.driver.assert_capture import AssertCapture


class TimedAssertCapture(AssertCapture):
    """
    AssertCapture implementation that also provides execution time of a test
    whose asserts are being captured.
    """

    def __init__(self, basis: AssertForwarder, test_index: Optional[int] = None):
        """
        Constructor

        :param basis: AssertForwarder
        :param test_index: Optional index of the test case for logging and reporting.
        """
        super().__init__(basis)
        self.execution_time_seconds: float = 0
        self.test_index: Optional[int] = test_index

    def set_execution_time(self, execution_time_seconds: float):
        """
        Set the execution time of the test whose asserts are being captured.

        :param execution_time_seconds: Execution time in seconds
        """
        self.execution_time_seconds = execution_time_seconds

    def get_execution_time(self) -> float:
        """
        Get the execution time of the test whose asserts are being captured.

        :return: Execution time in seconds
        """
        return self.execution_time_seconds

    def get_test_index(self) -> Optional[int]:
        """
        Get the index of the test case for logging and reporting.

        :return: Test index or None if not set
        """
        return self.test_index
