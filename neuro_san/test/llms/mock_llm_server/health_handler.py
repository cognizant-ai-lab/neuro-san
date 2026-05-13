
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


class HealthHandler(tornado.web.RequestHandler):
    """
    Liveness probe at GET /healthz. Returns a fixed JSON object so external
    schedulers (Kubernetes, Docker, etc.) can confirm the process is up.
    """

    def get(self) -> None:
        """Return a fixed liveness payload."""
        self.write({"status": "ok"})

    def data_received(self, chunk):
        """Required override of RequestHandler abstract method; no-op for GET."""
        return
