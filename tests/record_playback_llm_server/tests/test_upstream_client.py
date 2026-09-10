
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
Tests for UpstreamClient base-URL normalization.
"""
from tests.record_playback_llm_server.upstream_client import UpstreamClient


class TestUpstreamClient:
    """
    Base-URL normalization: the OpenAI-style /v1 segment is optional. Asserted
    through the public constructor's stored base_url.
    """

    @staticmethod
    def _base_url_for(configured: str) -> str:
        """Construct an UpstreamClient with the given base URL and return the normalized value."""
        return UpstreamClient(base_url=configured, api_key=None).base_url

    def test_appends_v1_when_absent(self):
        """A base URL without /v1 gets the version segment appended."""
        assert self._base_url_for("https://api.openai.com") == "https://api.openai.com/v1"

    def test_trailing_slash_stripped_then_v1_appended(self):
        """A trailing slash is stripped before appending /v1."""
        assert self._base_url_for("https://api.openai.com/") == "https://api.openai.com/v1"

    def test_existing_v1_left_as_is(self):
        """A base URL that already ends in /v1 is unchanged."""
        assert self._base_url_for("https://api.openai.com/v1") == "https://api.openai.com/v1"

    def test_existing_v1_trailing_slash_normalized(self):
        """A base URL ending in /v1/ is normalized to /v1 (no trailing slash)."""
        assert self._base_url_for("https://api.openai.com/v1/") == "https://api.openai.com/v1"

    def test_localhost_without_v1(self):
        """A host:port base URL without /v1 gets the segment appended."""
        assert self._base_url_for("http://localhost:9000") == "http://localhost:9000/v1"

    def test_empty_passed_through(self):
        """An empty base URL is passed through untouched (server enforces required-ness)."""
        assert self._base_url_for("") == ""
