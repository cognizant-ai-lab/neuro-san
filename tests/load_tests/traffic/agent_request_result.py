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

from typing import Any
from typing import Dict
from typing import Optional

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor


class AgentRequestResult:
    """
    Data-only holder for what one streaming_chat request produced.

    Built by ``AgentRequestExecutor.execute_request()`` and read by
    ``TrafficRunner`` to build the ``RequestResult`` that goes into the report.
    """

    # One argument per field of the request outcome; nothing to group.
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
            self,
            status: str,
            processor: Optional[BasicMessageProcessor],
            response_text: str,
            time_to_first_response: float,
            token_accounting: Dict[str, Any],
    ):
        """
        Constructor.

        :param status: STATUS_CREATED, STATUS_FAILED or STATUS_TIMEOUT
        :param processor: The BasicMessageProcessor that saw the whole stream
                          (answer, structure, sly_data); None when the request
                          did not complete
        :param response_text: The agent's final answer, or the traceback when
                              the request failed before completing
        :param time_to_first_response: Seconds until the first streamed
                                       message; 0.0 when none arrived
        :param token_accounting: Token usage reported by the server, empty
                                 when not available
        """
        self._status: str = status
        self._processor: Optional[BasicMessageProcessor] = processor
        self._response_text: str = response_text
        self._time_to_first_response: float = time_to_first_response
        self._token_accounting: Dict[str, Any] = token_accounting

    def get_status(self) -> str:
        """
        :return: STATUS_CREATED, STATUS_FAILED or STATUS_TIMEOUT
        """
        return self._status

    def get_processor(self) -> Optional[BasicMessageProcessor]:
        """
        :return: The message processor that saw the whole stream, or None
                 when the request did not complete
        """
        return self._processor

    def get_response_text(self) -> str:
        """
        :return: The agent's final answer, or the failure traceback
        """
        return self._response_text

    def get_time_to_first_response(self) -> float:
        """
        :return: Seconds until the first streamed message; 0.0 when none arrived
        """
        return self._time_to_first_response

    def get_token_accounting(self) -> Dict[str, Any]:
        """
        :return: Token usage reported by the server, empty when not available
        """
        return self._token_accounting
