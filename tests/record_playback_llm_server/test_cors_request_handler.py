
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

import json

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from typing import Dict

import tornado.web

from tornado.httpclient import HTTPResponse
from tornado.testing import AsyncHTTPTestCase
from typing_extensions import override

from record_playback_llm_server.cassette import Cassette
from record_playback_llm_server.cors_policy import CorsPolicy
from record_playback_llm_server.proxy_state import ProxyState
from record_playback_llm_server.record_playback_llm_server import RecordPlaybackLlmServer


class TestCorsRequestHandler(AsyncHTTPTestCase):
    """
    What the proxy's endpoints answer a browser page, over real HTTP.

    The application admits one origin, so the same requests show both the
    answer an admitted page gets and the answer every other page gets.
    """

    SITE: str = "http://alpha.localhost:8080"
    OTHER: str = "http://evil.localhost:8080"
    CHAT_PATH: str = "/v1/chat/completions"
    PAYLOAD: Dict[str, Any] = {"model": "m", "messages": [{"role": "user", "content": "hey"}]}

    @override
    def setUp(self) -> None:
        """
        Make a directory for the cassette before the application is built.

        :return: Nothing.
        """
        # pylint: disable=attribute-defined-outside-init
        # The object has to outlive this call, so the test case holds it and
        # cleans it up when the case ends.
        # pylint: disable=consider-using-with
        self.temp_dir: TemporaryDirectory = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        super().setUp()

    @override
    def get_app(self) -> tornado.web.Application:
        """
        Build the proxy with one admitted origin and an empty cassette.

        :return: The application under test.
        """
        # The cassette file does not exist, so every request is a playback miss.
        directory: Path = Path(self.temp_dir.name)
        cassette_file: Path = directory / "cassette.json"
        cassette_path: str = str(cassette_file)
        cassette: Cassette = Cassette(cassette_path, use_multi_mode=False)
        state: ProxyState = ProxyState(mode=ProxyState.MODE_PLAYBACK, cassette=cassette)
        policy: CorsPolicy = CorsPolicy([self.SITE])
        return RecordPlaybackLlmServer.build_app(state, policy)

    def preflight(self, origin: str) -> HTTPResponse:
        """
        Ask the question a browser asks before a cross-origin POST.

        :param origin: The origin to ask as.
        :return: The response.
        """
        headers: Dict[str, str] = {
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, authorization",
        }
        return self.fetch(self.CHAT_PATH, method="OPTIONS", body=None,
                          headers=headers, allow_nonstandard_methods=True)

    def test_a_preflight_from_an_admitted_origin_is_answered(self):
        """The browser is told the POST may go ahead."""
        response: HTTPResponse = self.preflight(self.SITE)
        allow_origin: str = response.headers.get("Access-Control-Allow-Origin")
        methods: str = response.headers.get("Access-Control-Allow-Methods")
        allowed: str = response.headers.get("Access-Control-Allow-Headers")
        self.assertEqual(204, response.code)
        self.assertEqual(self.SITE, allow_origin)
        self.assertIn("POST", methods)
        self.assertIn("authorization", allowed)

    def test_a_preflight_from_another_origin_is_refused(self):
        """An origin nobody admitted gets the answer it got before CORS existed."""
        response: HTTPResponse = self.preflight(self.OTHER)
        allow_origin: str = response.headers.get("Access-Control-Allow-Origin")
        self.assertEqual(405, response.code)
        self.assertIsNone(allow_origin)

    def test_an_admitted_page_may_read_an_ordinary_answer(self):
        """The permission header rides on the answer the page asked for."""
        headers: Dict[str, str] = {"Origin": self.SITE}
        response: HTTPResponse = self.fetch("/healthz", headers=headers)
        allow_origin: str = response.headers.get("Access-Control-Allow-Origin")
        vary: str = response.headers.get("Vary")
        self.assertEqual(200, response.code)
        self.assertEqual(self.SITE, allow_origin)
        self.assertEqual("Origin", vary)

    def test_another_page_may_not_read_an_ordinary_answer(self):
        """Without the header the browser hides the answer from the page."""
        headers: Dict[str, str] = {"Origin": self.OTHER}
        response: HTTPResponse = self.fetch("/healthz", headers=headers)
        allow_origin: str = response.headers.get("Access-Control-Allow-Origin")
        self.assertEqual(200, response.code)
        self.assertIsNone(allow_origin)

    def test_an_admitted_page_may_read_an_error_answer(self):
        """A playback miss is a 504, and the page must be able to see it."""
        body: str = json.dumps(self.PAYLOAD)
        headers: Dict[str, str] = {"Origin": self.SITE, "Content-Type": "application/json"}
        response: HTTPResponse = self.fetch(self.CHAT_PATH, method="POST", body=body,
                                            headers=headers, raise_error=False)
        allow_origin: str = response.headers.get("Access-Control-Allow-Origin")
        self.assertEqual(504, response.code)
        self.assertEqual(self.SITE, allow_origin)

    def test_a_caller_with_no_origin_is_answered_as_before(self):
        """A neuro-san process sends no Origin and gets no extra headers."""
        response: HTTPResponse = self.fetch("/healthz")
        allow_origin: str = response.headers.get("Access-Control-Allow-Origin")
        self.assertEqual(200, response.code)
        self.assertIsNone(allow_origin)
