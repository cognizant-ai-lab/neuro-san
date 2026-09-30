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


from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT


class RequestStatusPolicy:
    """
    Decides the status recorded for one load-test request.

    TIMEOUT when the request took at least --request-timeout, whether or not
    it raised; otherwise FAILED when it raised or produced no answer text,
    and CREATED when it produced one.
    """

    def __init__(self, timeout: float):
        """
        Constructor.

        :param timeout: Cap in seconds on the whole request (--request-timeout)
        """
        self._timeout: float = timeout

    def is_timed_out(self, elapsed: float) -> bool:
        """
        Tell whether a request has run out of --request-timeout.

        :param elapsed: Seconds the request has taken so far
        :return: True when the request has reached the cap
        """
        return elapsed >= self._timeout

    def status_for(self, elapsed: float, answer_text: str, error_text: str = "") -> str:
        """
        Decide the status of one finished request.

        :param elapsed: Seconds the request took
        :param answer_text: The final chat response text, empty when none
        :param error_text: Traceback text when the request raised, empty otherwise
        :return: STATUS_TIMEOUT, STATUS_FAILED or STATUS_CREATED
        """
        if self.is_timed_out(elapsed):
            return STATUS_TIMEOUT
        if error_text or not answer_text:
            return STATUS_FAILED
        return STATUS_CREATED

    @staticmethod
    def is_failure(status: str) -> bool:
        """
        Tell whether a recorded status counts as a failure.

        :param status: One of the STATUS_* values
        :return: True for FAILED, TIMEOUT and KILLED
        """
        return status in (STATUS_FAILED, STATUS_TIMEOUT, STATUS_KILLED)

    @staticmethod
    def is_traceback(status: str, response_text: str) -> bool:
        """
        Tell whether a FAILED request carries the traceback of the exception it raised as its response text.

        :param status: One of the STATUS_* values
        :param response_text: Response text of the request
        :return: True for a FAILED status with a response text
        """
        return status == STATUS_FAILED and bool(response_text)
