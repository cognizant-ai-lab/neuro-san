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


from tests.load_tests.load_test_constants import LoadTestConstants


class RequestStatusPolicy:
    """
    Decides the status recorded for one load-test request, and which
    recorded statuses count as failures or carry a traceback.

    TIMEOUT when the request took at least --request-timeout, whether or not
    it raised, or when no message came within the session's read timeout;
    otherwise FAILED when it raised or produced no answer text, and CREATED
    when it produced one.
    """

    def __init__(self, timeout_seconds: float) -> None:
        """
        Constructor.

        :param timeout_seconds: Cap in seconds on the whole request (--request-timeout)
        """
        self._timeout_seconds: float = timeout_seconds

    def is_timed_out(self, elapsed_seconds: float) -> bool:
        """
        Tell whether a request has run out of --request-timeout.

        :param elapsed_seconds: Seconds the request has taken so far
        :return: True when the request has reached the cap
        """
        return elapsed_seconds >= self._timeout_seconds

    def status_for(self, elapsed_seconds: float, answer_text: str, error_text: str = "",
                   read_timed_out: bool = False) -> str:
        """
        Decide the status of one finished request.

        :param elapsed_seconds: Seconds the request took
        :param answer_text: The final chat response text, empty when none
        :param error_text: Traceback text when the request raised, empty otherwise
        :param read_timed_out: True when the request raised because no message came within the read timeout
        :return: LoadTestConstants.STATUS_TIMEOUT, LoadTestConstants.STATUS_FAILED or
            LoadTestConstants.STATUS_CREATED
        """
        if self.is_timed_out(elapsed_seconds) or read_timed_out:
            return LoadTestConstants.STATUS_TIMEOUT
        if error_text or not answer_text:
            return LoadTestConstants.STATUS_FAILED
        return LoadTestConstants.STATUS_CREATED

    @staticmethod
    def is_failure(status: str) -> bool:
        """
        Tell whether a recorded status counts as a failure.

        :param status: One of the STATUS_* values
        :return: True for FAILED, TIMEOUT and KILLED
        """
        return status in [LoadTestConstants.STATUS_FAILED, LoadTestConstants.STATUS_TIMEOUT,
                          LoadTestConstants.STATUS_KILLED]

    @staticmethod
    def is_traceback(status: str, response_text: str) -> bool:
        """
        Tell whether a FAILED request carries the traceback of the exception it raised as its response text.

        :param status: One of the STATUS_* values
        :param response_text: Response text of the request
        :return: True for a FAILED status with a response text
        """
        return status == LoadTestConstants.STATUS_FAILED and bool(response_text)
