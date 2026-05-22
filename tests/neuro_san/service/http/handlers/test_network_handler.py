
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
"""Unit tests for NetworkHandler input validation.

Focus: the SAFE_AGENT_NAME_RE regex that guards the /network endpoint
against reflected XSS via the agent_name path parameter (CodeQL finding
on PR #943, where agent_name was interpolated into the Content-Disposition
header without sanitization).
"""
from __future__ import annotations

from neuro_san.service.http.handlers.network_handler import SAFE_AGENT_NAME_RE


class TestSafeAgentNameRegex:
    """The regex is the single source of truth for which agent names are
    safe to interpolate into response headers and bodies. Lock its
    accept/reject behavior down explicitly."""

    def test_accepts_typical_names(self):
        # Real names from the demo manifests.
        for name in [
            "trip_planner",
            "flight_finder",
            "hotel_finder",
            "music_nerd",
            "a",
            "A",
            "0",
            "agent-with-dashes",
            "agent_with_underscores",
            "Mixed_Case-123",
        ]:
            assert SAFE_AGENT_NAME_RE.match(name), f"should accept: {name!r}"

    def test_rejects_html_injection_payloads(self):
        for name in [
            "<script>alert(1)</script>",
            "agent\";alert(1)//",
            "agent</body>",
            "agent<img src=x onerror=alert(1)>",
        ]:
            assert not SAFE_AGENT_NAME_RE.match(name), f"should reject: {name!r}"

    def test_rejects_header_injection_payloads(self):
        # The Content-Disposition header was the original XSS vector; CRLF
        # in the agent name would let an attacker smuggle a new header.
        for name in [
            "agent\r\nX-Evil: 1",
            "agent\nX-Evil: 1",
            "agent\r",
            "agent\n",
            'agent"; filename="evil.html',
        ]:
            assert not SAFE_AGENT_NAME_RE.match(name), f"should reject: {name!r}"

    def test_rejects_path_traversal(self):
        for name in [
            "../etc/passwd",
            "a/b",
            "a\\b",
            "..",
            ".",
        ]:
            assert not SAFE_AGENT_NAME_RE.match(name), f"should reject: {name!r}"

    def test_rejects_empty_and_oversize(self):
        assert not SAFE_AGENT_NAME_RE.match("")
        # 129 chars — just over the cap.
        assert not SAFE_AGENT_NAME_RE.match("a" * 129)
        # 128 chars — right at the cap.
        assert SAFE_AGENT_NAME_RE.match("a" * 128)

    def test_rejects_unicode_lookalikes(self):
        # No Cyrillic/Greek lookalikes; ASCII-only by design.
        for name in [
            "аgent",   # Cyrillic 'а'
            "agent​",  # zero-width space
            "agent ",  # trailing space
            " agent",  # leading space
        ]:
            assert not SAFE_AGENT_NAME_RE.match(name), f"should reject: {name!r}"

    def test_rejects_control_bytes(self):
        for name in [
            "agent\x00",
            "agent\x1b[31m",
            "\x00agent",
        ]:
            assert not SAFE_AGENT_NAME_RE.match(name), f"should reject: {name!r}"
