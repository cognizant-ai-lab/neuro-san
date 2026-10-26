
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

from __future__ import annotations

from typing import Any
from typing import Dict
from typing import Optional

from typing_extensions import override

import tornado.web

from tests.record_playback_llm_server.cors_policy import CorsPolicy


class CorsRequestHandler(tornado.web.RequestHandler):
    """
    The base of every endpoint of this proxy, which answers a browser as well
    as a neuro-san process.

    The permission headers go on in set_default_headers, which Tornado calls
    for the first answer and again after every clear(), so an error answer
    carries them too. Without them a browser hides the answer from the page
    that asked, whatever the status code is.

    The policy comes from the application settings rather than from each
    route, so a route needs no change to admit a browser.
    """

    SETTING_NAME: str = "cors_policy"

    def cors_policy(self) -> CorsPolicy:
        """
        Read the policy this server runs with.

        :return: The policy, or an empty one that admits nothing.
        """
        settings: Dict[str, Any] = self.settings
        policy: Optional[CorsPolicy] = settings.get(CorsRequestHandler.SETTING_NAME)
        if policy is None:
            return CorsPolicy()
        return policy

    def request_origin(self) -> str:
        """
        Read the origin of the page that made the request.

        :return: The Origin header, or "" when the caller sent none, which is
                 what a neuro-san process does.
        """
        headers: Dict[str, str] = self.request.headers
        return headers.get("Origin", "")

    def requested_headers(self) -> str:
        """
        Read the headers a browser says its real call needs.

        :return: The Access-Control-Request-Headers value, or "" when the
                 caller sent none.
        """
        headers: Dict[str, str] = self.request.headers
        return headers.get("Access-Control-Request-Headers", "")

    @override
    def set_default_headers(self) -> None:
        """
        Put the permission headers on every answer this handler writes.

        :return: Nothing.
        """
        policy: CorsPolicy = self.cors_policy()
        origin: str = self.request_origin()
        headers: Dict[str, str] = policy.response_headers(origin)
        name: str = ""
        value: str = ""
        # Tornado has already cleared the headers, so set each one again.
        for name, value in headers.items():
            self.set_header(name, value)

    @override
    def options(self, *args: str) -> None:
        """
        Answer the preflight question a browser asks before a real call.

        :param args: The path parts of the route, which no route of this
                     server uses.
        :return: Nothing.
        :raises HTTPError: 405 when the origin is not one the policy admits,
                           which is how this server answered before any origin
                           was admitted.
        """
        policy: CorsPolicy = self.cors_policy()
        origin: str = self.request_origin()
        asked: str = self.requested_headers()
        headers: Dict[str, str] = policy.preflight_headers(origin, asked)
        if not headers:
            super().options(*args)
            return
        name: str = ""
        value: str = ""
        # The preflight answer needs the methods and headers as well.
        for name, value in headers.items():
            self.set_header(name, value)
        self.set_status(204)
        self.finish()

    @override
    def data_received(self, chunk: bytes) -> None:
        """
        Fulfill the abstract method of RequestHandler.

        :param chunk: The bytes that arrived, which this server never streams in.
        :return: Nothing.
        """
        return
