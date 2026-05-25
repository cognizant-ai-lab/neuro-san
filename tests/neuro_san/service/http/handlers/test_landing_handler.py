
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

from neuro_san.service.http.handlers.landing_handler import (
    LandingHandler,
    _branding_to_css_vars,
    _summarize_tool_graph,
)


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
        assert "no published networks" in html.lower()
        assert "publish: true" in html

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


# ---------- _branding_to_css_vars ----------


class TestBrandingToCssVars:
    def test_emits_expected_variables(self):
        branding = {
            "primary_color": "#0033A0",
            "accent_color":  "#E1241B",
            "background":    "#F4F7FB",
            "foreground":    "#0a1d3f",
            "muted":         "#5d6a85",
            "card":          "#ffffff",
            "font_stack":    "Helvetica, Arial, sans-serif",
        }
        css = _branding_to_css_vars(branding)
        assert "--brand-primary: #0033A0;" in css
        assert "--brand-accent: #E1241B;" in css
        assert "--brand-bg: #F4F7FB;" in css
        assert "--brand-fg: #0a1d3f;" in css
        assert "--brand-muted: #5d6a85;" in css
        assert "--brand-card: #ffffff;" in css
        assert "--brand-font: Helvetica, Arial, sans-serif;" in css

    def test_skips_unknown_keys(self):
        css = _branding_to_css_vars({"name": "Foo", "logo": "🔥", "primary_color": "#abc"})
        assert "--brand-primary: #abc;" in css
        # name/logo are bootstrap-only, not CSS.
        assert "Foo" not in css
        assert "🔥" not in css

    def test_rejects_injection_payloads(self):
        branding = {
            "primary_color": "red; } body { display: none } /*",
            "accent_color":  "#abc",
        }
        css = _branding_to_css_vars(branding)
        # The malicious value must be rejected entirely.
        assert "display: none" not in css
        assert "--brand-primary" not in css
        # The clean one passes.
        assert "--brand-accent: #abc;" in css

    def test_empty_dict_returns_empty_string(self):
        assert _branding_to_css_vars({}) == ""

    def test_non_string_values_ignored(self):
        css = _branding_to_css_vars({"primary_color": 123, "accent_color": None,
                                      "background": "#fff"})
        assert "--brand-primary" not in css
        assert "--brand-accent" not in css
        assert "--brand-bg: #fff;" in css


# ---------- _summarize_tool_graph ----------


class TestSummarizeToolGraph:
    def test_basic_front_man_with_internal_tool(self):
        config = {
            "tools": [
                {"name": "front",  "instructions": "...", "tools": ["calc"]},
                {"name": "calc",   "function": {"description": "math"},
                 "class": "calc.Calc"},
            ],
        }
        nodes = _summarize_tool_graph(config)
        assert nodes[0]["name"] == "front"
        assert nodes[0]["kind"] == "front_man"
        assert nodes[0]["tools"] == ["calc"]
        assert nodes[1]["name"] == "calc"
        assert nodes[1]["kind"] == "coded_tool"

    def test_cross_origin_tool_reference(self):
        config = {
            "tools": [
                {"name": "trip", "tools": [
                    "http://flights.example:8801/flight_finder",
                ]},
            ],
        }
        nodes = _summarize_tool_graph(config)
        # Front man is trip; child is the cross-origin agent extracted from URL.
        assert nodes[0]["name"] == "trip"
        assert nodes[0]["tools"] == ["flight_finder"]
        child = nodes[1]
        assert child["name"] == "flight_finder"
        assert child["kind"] == "cross_origin"
        assert child["url"] == "http://flights.example:8801/flight_finder"

    def test_client_side_tool(self):
        config = {
            "tools": [
                {"name": "trip", "tools": ["total_cost"]},
                {"name": "total_cost", "client_side": True,
                 "class": "total_cost.TotalCost"},
            ],
        }
        nodes = _summarize_tool_graph(config)
        assert nodes[1]["kind"] == "client_side"

    def test_internal_llm_subagent(self):
        # Sub-agent with no class/toolbox/client_side = another LLM agent
        config = {
            "tools": [
                {"name": "front", "tools": ["helper"]},
                {"name": "helper", "function": {"description": "...",
                                                "parameters": {"type": "object",
                                                               "properties": {}}}},
            ],
        }
        nodes = _summarize_tool_graph(config)
        assert nodes[1]["kind"] == "internal_agent"

    def test_missing_tool_reference_marked_unknown(self):
        config = {
            "tools": [
                {"name": "front", "tools": ["ghost"]},
            ],
        }
        nodes = _summarize_tool_graph(config)
        assert nodes[1]["name"] == "ghost"
        assert nodes[1]["kind"] == "unknown"

    def test_empty_config(self):
        assert _summarize_tool_graph({}) == []
        assert _summarize_tool_graph({"tools": []}) == []

    def test_function_name_takes_precedence(self):
        # When function.name is set, that's the canonical name (consistent
        # with AgentNetwork.get_name_from_spec).
        config = {
            "tools": [
                {"function": {"name": "the_front"}, "tools": []},
            ],
        }
        nodes = _summarize_tool_graph(config)
        assert nodes[0]["name"] == "the_front"

    def test_dict_tool_ref_is_skipped(self):
        # Dict tool refs (MCP servers) are out of scope for the demo viz.
        config = {
            "tools": [
                {"name": "front", "tools": [{"url": "https://mcp.x/"}, "calc"]},
                {"name": "calc", "class": "calc.Calc"},
            ],
        }
        nodes = _summarize_tool_graph(config)
        # Only 'calc' should be in the front-man's tools list.
        assert nodes[0]["tools"] == ["calc"]


# ---------- branding pickup in _collect_published_networks ----------


class TestBrandingPickup:
    def test_render_with_bootstrap_injects_css_when_branding_present(self):
        template = "<html><head></head><body></body></html>"
        branding = {"primary_color": "#abc", "name": "TestBrand"}
        out = LandingHandler._render_with_bootstrap(
            template, "http://x.example", [], branding=branding,
        )
        assert "--brand-primary: #abc;" in out
        # And the bootstrap JSON includes the branding so JS can read name/logo.
        assert "TestBrand" in out

    def test_render_with_bootstrap_skips_css_block_when_no_branding(self):
        template = "<html><head></head><body></body></html>"
        out = LandingHandler._render_with_bootstrap(
            template, "http://x.example", [], branding=None,
        )
        # No <style> block since there's nothing to declare.
        assert "<style>" not in out

    def test_pick_branding_finds_first_with_branding(self):
        handler = _stub_handler()
        networks = [
            {"name": "no_branding"},
            {"name": "has_branding", "branding": {"name": "X"}},
            {"name": "also_branded", "branding": {"name": "Y"}},
        ]
        assert handler._pick_branding(networks) == {"name": "X"}

    def test_pick_branding_empty_when_none(self):
        handler = _stub_handler()
        assert handler._pick_branding([{"name": "a"}, {"name": "b"}]) == {}
