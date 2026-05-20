
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
"""Unit tests for LandingHandler's rendering helpers (the pure-function bits).

We don't spin up Tornado; instead we exercise the rendering helpers directly,
which is where all the interesting logic lives.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from neuro_san.service.http.handlers.landing_handler import LandingHandler


# ---------- _render_default ----------


class TestRenderDefault:
    def test_renders_origin_in_title(self):
        html = LandingHandler._render_default(
            "http://flights.example:8801", []
        )
        assert "flights.example:8801" in html
        assert "Agent Web" in html

    def test_no_networks_message(self):
        html = LandingHandler._render_default("http://flights.example", [])
        assert "no distributable networks" in html.lower()
        assert "distributable: true" in html

    def test_lists_networks(self):
        networks = [
            {
                "name": "flight_finder",
                "description": "Searches private flight inventory.",
                "url": "http://flights.example/api/v1/flight_finder/network",
            },
            {
                "name": "ledger",
                "description": "",
                "url": "http://flights.example/api/v1/ledger/network",
            },
        ]
        html = LandingHandler._render_default("http://flights.example", networks)
        assert "flight_finder" in html
        assert "Searches private flight inventory." in html
        assert "http://flights.example/api/v1/flight_finder/network" in html
        assert "ledger" in html
        # Empty description gets a placeholder.
        assert "(no description)" in html

    def test_html_escaping_prevents_injection(self):
        networks = [
            {
                "name": "<script>alert(1)</script>",
                "description": "</body><img onerror=alert(1)>",
                "url": "javascript:alert(1)",
            },
        ]
        html = LandingHandler._render_default("http://x.example", networks)
        # Raw script tag must not appear; escaped form must.
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "</body><img" not in html

    def test_origin_is_escaped(self):
        html = LandingHandler._render_default(
            "http://evil.example?<script>alert(1)</script>", []
        )
        assert "<script>alert(1)</script>" not in html


# ---------- _render_with_bootstrap ----------


class TestRenderWithBootstrap:
    def test_injects_bootstrap_script_into_head(self):
        template = (
            "<!doctype html><html><head><title>X</title></head>"
            "<body>Y</body></html>"
        )
        html = LandingHandler._render_with_bootstrap(
            template,
            "http://flights.example",
            [{"name": "n1", "description": "d1", "url": "/u1"}],
        )
        # The original template content survives.
        assert "<title>X</title>" in html
        assert "<body>Y</body>" in html
        # The bootstrap appears BEFORE </head>.
        head_close = html.lower().index("</head>")
        bootstrap_pos = html.index("AGENT_WEB_BOOTSTRAP")
        assert bootstrap_pos < head_close

    def test_bootstrap_data_is_valid_json(self):
        template = "<html><head></head><body></body></html>"
        networks = [
            {"name": "n", "description": "d", "url": "/u",
             "sample_queries": ["q1", "q2"]},
        ]
        html = LandingHandler._render_with_bootstrap(
            template, "http://origin.example", networks,
        )
        # Pull out the bootstrap JSON literal.
        start = html.index("window.AGENT_WEB_BOOTSTRAP = ") + len(
            "window.AGENT_WEB_BOOTSTRAP = "
        )
        end = html.index(";\n", start)
        bootstrap = json.loads(html[start:end])
        assert bootstrap["origin"] == "http://origin.example"
        assert bootstrap["networks"] == networks

    def test_missing_head_prepends_script(self):
        template = "<html>no-head-tag-here</html>"
        html = LandingHandler._render_with_bootstrap(
            template, "http://x.example", [],
        )
        # No </head>, so bootstrap should be at the very start.
        assert html.startswith("<script>")


# ---------- _render dispatch ----------


class TestRenderDispatch:
    def test_falls_back_to_default_when_no_static_dir(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("AGENT_STATIC_DIR", raising=False)
        handler = _stub_handler()
        html = handler._render("http://x.example", [])
        assert "Agent Web" in html
        # Default template has no bootstrap script.
        assert "AGENT_WEB_BOOTSTRAP" not in html

    def test_uses_static_index_html_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # Drop a minimal index.html in a tmp dir.
        index = tmp_path / "index.html"
        index.write_text(
            "<!doctype html><html><head><meta charset=\"utf-8\"></head>"
            "<body><script src=\"app.js\"></script></body></html>",
            encoding="utf-8",
        )
        monkeypatch.setenv("AGENT_STATIC_DIR", str(tmp_path))
        handler = _stub_handler()
        html = handler._render(
            "http://flights.example",
            [{"name": "x", "description": "d", "url": "/u"}],
        )
        # We should see the template content AND the bootstrap.
        assert "<meta charset=\"utf-8\">" in html
        assert "AGENT_WEB_BOOTSTRAP" in html
        assert "flights.example" in html

    def test_missing_index_falls_back_to_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # AGENT_STATIC_DIR set, but no index.html.
        monkeypatch.setenv("AGENT_STATIC_DIR", str(tmp_path))
        handler = _stub_handler()
        html = handler._render("http://x.example", [])
        assert "Agent Web" in html
        assert "AGENT_WEB_BOOTSTRAP" not in html


def _stub_handler() -> LandingHandler:
    """Build a LandingHandler bypassing Tornado's __init__ so we can test
    the pure-rendering methods. We never touch attributes that the real
    handler relies on at request time."""
    return LandingHandler.__new__(LandingHandler)
