
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

from typing import Dict

import tornado.web


class CountingUpstream(tornado.web.RequestHandler):
    """Fake OpenAI upstream returning a distinct body ("resp-N") per call."""

    def initialize(self, box: Dict[str, int]) -> None:
        """Receive a shared call-counter box from the application."""
        # pylint: disable=attribute-defined-outside-init
        self.box = box

    def data_received(self, chunk):
        """Unused; the full body arrives via self.request.body."""
        return

    async def post(self) -> None:
        """Return a one-shot completion whose content increments each call."""
        self.box["n"] += 1
        self.write({
            "id": "chatcmpl-fake", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": f"resp-{self.box['n']}"},
                         "finish_reason": "stop"}],
        })
