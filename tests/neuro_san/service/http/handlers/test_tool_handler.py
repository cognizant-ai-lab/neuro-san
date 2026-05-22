
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
"""Unit tests for ToolHandler input validation.

The /tool/ endpoint takes TWO user-controlled path parameters
(agent_name and tool_name); both are interpolated into request-rate
accounting strings and log lines. Each must pass the same safe-identifier
regex as the /network endpoint. CodeQL flagged the sister handler
(NetworkHandler) on PR #943; this handler shares the same shape and gets
the same lockdown.
"""
from __future__ import annotations

from neuro_san.service.http.handlers.tool_handler import SAFE_NAME_RE


class TestSafeNameRegex:

    def test_accepts_typical_agent_and_tool_names(self):
        for name in [
            "trip_planner",
            "flight_finder",
            "search_flights",
            "calc",
            "a",
            "Z9",
            "with-dashes",
            "with_underscores_123",
        ]:
            assert SAFE_NAME_RE.match(name), f"should accept: {name!r}"

    def test_rejects_html_and_header_injection(self):
        # If either agent_name OR tool_name slips through, an attacker can
        # smuggle CRLF or HTML payloads into log lines / response bodies.
        for name in [
            "<script>",
            "agent\r\nSet-Cookie: x=y",
            "agent\nX-Evil: 1",
            'tool"; filename="evil.html',
            "tool</body>",
        ]:
            assert not SAFE_NAME_RE.match(name), f"should reject: {name!r}"

    def test_rejects_path_traversal(self):
        for name in [
            "../etc/passwd",
            "a/b",
            "a\\b",
            "..",
        ]:
            assert not SAFE_NAME_RE.match(name), f"should reject: {name!r}"

    def test_rejects_empty_and_oversize(self):
        assert not SAFE_NAME_RE.match("")
        assert not SAFE_NAME_RE.match("a" * 129)
        assert SAFE_NAME_RE.match("a" * 128)

    def test_rejects_control_bytes(self):
        for name in [
            "agent\x00",
            "\x1bagent",
            "ag\x07ent",
        ]:
            assert not SAFE_NAME_RE.match(name), f"should reject: {name!r}"

    def test_rejects_whitespace(self):
        for name in [
            " agent",
            "agent ",
            "two words",
            "tab\tname",
        ]:
            assert not SAFE_NAME_RE.match(name), f"should reject: {name!r}"
