
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
Pytest fixtures for the record/playback proxy tests.
"""
from typing import List

import pytest

import tornado.httpserver
import tornado.web

from tornado.testing import bind_unused_port


@pytest.fixture(autouse=True)
def configure_llm_provider_keys():
    """
    Override the repo-wide autouse fixture of the same name (tests/conftest.py),
    which skips tests when no LLM provider API key is present. These proxy tests
    drive a local in-process fake upstream and never contact a real LLM, so no
    provider key is required.
    """
    yield


@pytest.fixture
def start_app():
    """
    Return a factory that binds a Tornado app to an unused loopback port and
    returns its base URL; all started servers are stopped on teardown.
    """
    servers: List[tornado.httpserver.HTTPServer] = []

    def _start(app: tornado.web.Application) -> str:
        sock, port = bind_unused_port()
        server = tornado.httpserver.HTTPServer(app)
        server.add_socket(sock)
        servers.append(server)
        return f"http://127.0.0.1:{port}"

    try:
        yield _start
    finally:
        for server in servers:
            server.stop()
