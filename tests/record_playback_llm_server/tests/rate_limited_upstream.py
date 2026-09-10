
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

import tornado.web


class RateLimitedUpstream(tornado.web.RequestHandler):
    """Fake OpenAI upstream that always rate-limits with HTTP 429."""

    def data_received(self, chunk):
        """Unused; the full body arrives via self.request.body."""
        return

    async def post(self) -> None:
        """Always respond 429 Too Many Requests."""
        self.set_status(429)
        self.write({"error": {"message": "Too Many Requests"}})
