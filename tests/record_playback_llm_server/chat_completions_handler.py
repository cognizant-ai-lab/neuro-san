
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


class ChatCompletionsHandler(ProxyHandler):
    """
    Implements POST /v1/chat/completions by recording against, or replaying
    from, the cassette. The streaming vs one-shot decision is taken from the
    request body's `stream` flag, exactly as a real OpenAI endpoint would.
    """

    async def post(self) -> None:
        """Record or replay a chat-completions request."""
        await self.handle_request("POST", self.request.body or b"")
