
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

from json import loads
from requests import get

from neuro_san.interfaces.concierge_session import ConciergeSession
from neuro_san.session.abstract_http_service_agent_session import AbstractHttpServiceAgentSession


class HttpConciergeSession(AbstractHttpServiceAgentSession, ConciergeSession):
    """
    Implementation of ConciergeSession that talks to an HTTP service.
    This is largely only used by command-line tests.
    """

    def list(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the ConciergeRequest
                    protobuf structure. Has the following keys:
                        <None>
        :return: A dictionary version of the ConciergeResponse
                    protobuf structure. Has the following keys:
                "agents" - the sequence of dictionaries describing available agents
        """
        path: str = self.get_request_path("list")
        try:
            response = get(path, json=request_dict, headers=self.get_headers(),
                           timeout=self.timeout_in_seconds)
            result_dict = loads(response.text)
            return result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc
