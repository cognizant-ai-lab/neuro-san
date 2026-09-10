
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

import json

from typing import Any
from typing import Dict
from typing import Tuple

import tornado.httpclient

from tests.record_playback_llm_server.upstream_client import UpstreamClient


class ProxyTestClient:
    """
    Async HTTP helpers and shared constants used by the proxy integration tests
    to drive requests at the in-process proxy/upstream apps.
    """

    CHAT_PATH: str = "/v1/chat/completions"
    PAYLOAD: Dict[str, Any] = {"model": "m", "messages": [{"role": "user", "content": "hey"}]}

    @staticmethod
    async def post(url: str, payload: Dict[str, Any], stream: bool = False) -> Tuple[int, bytes]:
        """POST JSON to url; when stream=True, accumulate and return the streamed body."""
        client = tornado.httpclient.AsyncHTTPClient(force_instance=True)
        body: Dict[str, Any] = {**payload, "stream": True} if stream else payload
        chunks = bytearray()
        response = await client.fetch(
            url, method="POST", body=json.dumps(body),
            headers={"Content-Type": "application/json"},
            streaming_callback=(chunks.extend if stream else None),
            request_timeout=30, raise_error=False)
        return response.code, (bytes(chunks) if stream else response.body)

    @staticmethod
    def content(body: bytes) -> str:
        """Extract the assistant text from a one-shot chat completion body."""
        return json.loads(body)["choices"][0]["message"]["content"]

    @staticmethod
    def upstream_client(base_url: str) -> UpstreamClient:
        """Build an UpstreamClient pointed at a fake upstream's /v1 base."""
        return UpstreamClient(base_url=f"{base_url}/v1", api_key=None)
