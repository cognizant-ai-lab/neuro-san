
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from typing import Any
from typing import Dict

import json
import requests

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
            response = requests.get(path, json=request_dict, headers=self.get_headers(),
                                    timeout=self.timeout_in_seconds)
            result_dict = json.loads(response.text)
            return result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc
