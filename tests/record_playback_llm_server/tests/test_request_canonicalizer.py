
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
Tests for RequestCanonicalizer key stability.
"""
import json

from tests.record_playback_llm_server.request_canonicalizer import RequestCanonicalizer


class TestRequestCanonicalizer:
    """Canonical-key stability guarantees the record/playback matching relies on."""

    def test_key_ignores_json_key_order(self):
        """Requests differing only in JSON key order hash to the same key."""
        body_a = json.dumps({"model": "m", "stream": False, "messages": []}).encode()
        body_b = json.dumps({"messages": [], "stream": False, "model": "m"}).encode()
        assert RequestCanonicalizer.key("POST", "/v1/chat/completions", body_a) == \
            RequestCanonicalizer.key("POST", "/v1/chat/completions", body_b)

    def test_stream_flag_changes_key(self):
        """A streamed request and a one-shot request map to different keys."""
        one = json.dumps({"model": "m", "stream": False}).encode()
        streamed = json.dumps({"model": "m", "stream": True}).encode()
        assert RequestCanonicalizer.key("POST", "/v1/chat/completions", one) != \
            RequestCanonicalizer.key("POST", "/v1/chat/completions", streamed)

    def test_path_and_method_participate(self):
        """Method and path are part of the key, not just the body."""
        body = b"{}"
        assert RequestCanonicalizer.key("POST", "/chat/completions", body) != \
            RequestCanonicalizer.key("GET", "/chat/completions", body)
