
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

from tests.record_playback_llm_server.proxy_handler import ProxyHandler


class ModelsHandler(ProxyHandler):
    """
    Implements GET /v1/models by recording against, or replaying from, the
    cassette. Most LangChain chat clients never call this, but it is proxied
    for parity with a real OpenAI endpoint so clients that introspect models
    still work fully offline in playback.
    """

    async def get(self) -> None:
        """Record or replay a models-list request."""
        await self.handle_request("GET", b"")
