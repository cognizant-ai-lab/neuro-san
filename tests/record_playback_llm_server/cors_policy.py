
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

from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple


class CorsPolicy:
    """
    The cross-origin rules the proxy answers with.

    A browser page that calls this proxy is on an origin of its own, so the
    browser sends a preflight request first and then checks the response for
    permission headers. Nothing of that is needed by a neuro-san process, which
    is why the policy is off until an operator names the origins to admit.

    An origin is either an exact match, such as "http://alpha.localhost:8080",
    or the wildcard "*", which admits every page. Credentials are never allowed:
    the proxy holds no cookie or session, and the visitor's key travels in an
    Authorization header, which CORS treats as an ordinary header.
    """

    WILDCARD: str = "*"

    DEFAULT_ALLOWED_HEADERS: Tuple[str, ...] = ("authorization", "content-type")

    ALLOWED_METHODS: Tuple[str, ...] = ("GET", "POST", "OPTIONS")

    PREFLIGHT_MAX_AGE_SECONDS: int = 600

    def __init__(self, origins: Optional[List[str]] = None):
        """
        Constructor

        :param origins: The origins to admit, or None to admit none. The single
                        entry "*" admits every origin.
        """
        self.origins: List[str] = []
        self.allow_any: bool = False
        given: List[str] = origins or []
        origin: str = ""
        # Hold the origins in the form the Origin header arrives in.
        for origin in given:
            normal: str = CorsPolicy.normalize(origin)
            if not normal:
                continue
            if normal == CorsPolicy.WILDCARD:
                self.allow_any = True
                continue
            if normal not in self.origins:
                self.origins.append(normal)

    @staticmethod
    def normalize(origin: str) -> str:
        """
        Put an origin in the form an Origin header carries it.

        :param origin: The origin as an operator or a browser wrote it.
        :return: The origin in lower case with no trailing slash, or "" when
                 there is nothing to compare.
        """
        text: str = str(origin or "")
        trimmed: str = text.strip()
        without_slash: str = trimmed.rstrip("/")
        return without_slash.lower()

    @staticmethod
    def from_values(values: Optional[List[str]]) -> "CorsPolicy":
        """
        Build a policy from command line values, each of which can be a list.

        :param values: The --allow-origin values, each one origin or several
                       separated by commas.
        :return: The policy the values describe.
        """
        origins: List[str] = []
        given: List[str] = values or []
        value: str = ""
        # Each flag can carry a comma separated list, so split every one.
        for value in given:
            if not value:
                continue
            text: str = str(value)
            parts: List[str] = text.split(",")
            part: str = ""
            for part in parts:
                stripped: str = part.strip()
                if stripped:
                    origins.append(stripped)
        return CorsPolicy(origins)

    def is_enabled(self) -> bool:
        """
        Report whether the policy admits anything at all.

        :return: True when at least one origin is admitted.
        """
        has_named: bool = bool(self.origins)
        return self.allow_any or has_named

    def allows(self, origin: str) -> bool:
        """
        Report whether a page on one origin may read this server's answers.

        :param origin: The value of the request's Origin header.
        :return: True when the origin is admitted.
        """
        enabled: bool = self.is_enabled()
        if not enabled:
            return False
        normal: str = CorsPolicy.normalize(origin)
        if not normal:
            return False
        is_named: bool = normal in self.origins
        return self.allow_any or is_named

    def response_headers(self, origin: str) -> Dict[str, str]:
        """
        Build the headers that let the calling page read an ordinary answer.

        :param origin: The value of the request's Origin header.
        :return: The headers to set, empty when the origin is not admitted.
        """
        headers: Dict[str, str] = {}
        admitted: bool = self.allows(origin)
        if not admitted:
            return headers
        if self.allow_any:
            headers["Access-Control-Allow-Origin"] = CorsPolicy.WILDCARD
            return headers
        normal: str = CorsPolicy.normalize(origin)
        headers["Access-Control-Allow-Origin"] = normal
        # The answer differs by origin, so caches must key on the header.
        headers["Vary"] = "Origin"
        return headers

    def preflight_headers(self, origin: str, requested_headers: str = "") -> Dict[str, str]:
        """
        Build the headers that answer a browser's preflight question.

        :param origin: The value of the request's Origin header.
        :param requested_headers: The value of the request's
                                  Access-Control-Request-Headers, when it sent one.
        :return: The headers to set, empty when the origin is not admitted.
        """
        headers: Dict[str, str] = self.response_headers(origin)
        if not headers:
            return headers
        methods: str = ", ".join(CorsPolicy.ALLOWED_METHODS)
        allowed: str = self.allowed_headers(requested_headers)
        max_age: str = str(CorsPolicy.PREFLIGHT_MAX_AGE_SECONDS)
        headers["Access-Control-Allow-Methods"] = methods
        headers["Access-Control-Allow-Headers"] = allowed
        headers["Access-Control-Max-Age"] = max_age
        return headers

    def allowed_headers(self, requested_headers: str) -> str:
        """
        Decide which request headers the calling page may send.

        :param requested_headers: The value of Access-Control-Request-Headers.
        :return: The header names to admit, as one comma separated string.
        """
        text: str = str(requested_headers or "")
        asked: str = text.strip()
        if asked:
            # The browser lists exactly what the call needs. A proxy that
            # records and replays has no reason to refuse a header.
            return asked
        return ", ".join(CorsPolicy.DEFAULT_ALLOWED_HEADERS)
