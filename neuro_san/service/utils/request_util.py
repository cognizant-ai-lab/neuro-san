
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
"""
See class comment for details
"""
from typing import Union

import html


class RequestUtil:
    """
    Utility class for sanitizing user-controlled values that flow back into
    HTTP / MCP responses, so HTML-based consumers cannot be tricked into
    rendering unescaped client input.
    """

    @staticmethod
    def safe_request_id(request_id: Union[int, str]) -> str:
        """
        Return HTML-safe representation of a user-supplied request id to be
        echoed back in a response.
        :param request_id: request id (as received from the user);
        :return: HTML-escaped request id string.
        """
        # Always return a string and always HTML-escape it to avoid XSS
        # vulnerabilities in any HTML-based consumers of the response.
        if isinstance(request_id, str):
            return html.escape(request_id)
        # For non-string IDs (including integers), convert to string first,
        # then escape to ensure the returned value is HTML-safe.
        return html.escape(str(request_id))

    @staticmethod
    def safe_message(msg: str) -> str:
        """
        Return HTML-safe representation of a string message to be echoed back
        in a response.
        :param msg: message string;
        :return: HTML-escaped message string.
        """
        return html.escape(msg)
