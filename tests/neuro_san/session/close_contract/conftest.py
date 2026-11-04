
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
Pytest fixtures for the agent-session close()/is_closed() contract tests
in this directory (test_http_service_agent_session_close.py and
test_async_http_service_agent_session_close.py).
"""
import pytest

from tests.neuro_san.session.close_contract.streaming_cancel_server import StreamingCancelServer


@pytest.fixture
def streaming_cancel_server():
    """
    Start an in-process StreamingCancelServer for a single test and stop it on
    teardown. Used by the transport-level close()-cancellation tests to drive a
    real agent session into a blocked state before cancelling it.
    """
    server: StreamingCancelServer = StreamingCancelServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()
