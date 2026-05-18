
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
See class comment for details.
"""
from __future__ import annotations

import time

import tornado.web

from tests.mock_llm_server.mock_state import MockState


class ModelsHandler(tornado.web.RequestHandler):
    """
    Implements GET /v1/models so OpenAI-style clients can introspect the
    list of available models. The mock server reports exactly one model
    whose name is the value configured in MockState.model_name.
    """

    def initialize(self, state: MockState) -> None:
        """Receive the shared MockState from the Tornado application."""
        # pylint: disable=attribute-defined-outside-init
        self.state = state

    def get(self) -> None:
        """Return a one-entry list containing the mock model."""
        self.write(
            {
                "object": "list",
                "data": [
                    {
                        "id": self.state.model_name,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "mock",
                    }
                ],
            }
        )

    def data_received(self, chunk):
        """Required override of RequestHandler abstract method; no-op for GET."""
        return
