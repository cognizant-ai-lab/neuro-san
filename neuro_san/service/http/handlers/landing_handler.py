
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
LandingHandler — serves an HTML index of the origin's distributable networks
at GET /.

Opt-in via the AGENT_LANDING_ENABLE env var (or set in HttpServerConfig). When
disabled, the route falls back to the previous HealthCheckHandler behavior.

The page is essentially the static "Agent Web Browser" index.html with a
small JSON bootstrap block injected at the top so the page knows what this
origin publishes without making a second request.
"""
import json
import os
from html import escape
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, List

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.run_context.utils.external_agent_parsing import ExternalAgentParsing
from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler


# Mapping from branding-dict keys to CSS custom property names.
_BRANDING_CSS_KEYS: Dict[str, str] = {
    "primary_color":   "--brand-primary",
    "accent_color":    "--brand-accent",
    "background":      "--brand-bg",
    "foreground":      "--brand-fg",
    "muted":           "--brand-muted",
    "card":            "--brand-card",
    "font_stack":      "--brand-font",
}


def _branding_to_css_vars(branding: Dict[str, Any]) -> str:
    """Translate a branding dict into CSS custom-property declarations.
    Only keys in _BRANDING_CSS_KEYS produce output; unknown keys are ignored
    (they may still be read from the JS bootstrap)."""
    lines: List[str] = []
    for src_key, css_var in _BRANDING_CSS_KEYS.items():
        value = branding.get(src_key)
        if not isinstance(value, str) or not value:
            continue
        # Conservative validation: reject anything containing characters that
        # could close the <style> block or inject other declarations.
        if any(c in value for c in (";", "{", "}", "<", ">")):
            continue
        lines.append(f"    {css_var}: {value};")
    return "\n".join(lines)


def _summarize_tool_graph(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract a graph summary suitable for client-side visualization:
        [
          {"name": "trip_planner", "kind": "front_man", "tools": ["...", "..."]},
          {"name": "flight_finder", "kind": "cross_origin",
           "url": "http://localhost:8801/flight_finder"},
          {"name": "total_cost", "kind": "client_side"},
          ...
        ]

    Classification matches the dispatch logic in ActivationFactory:
      * front_man: the first agent in the network (no class/toolbox/url)
      * cross_origin: tool reference is a URL (starts with http(s):// or /)
      * client_side: agent spec has client_side: true
      * coded_tool: agent has `class` or `toolbox` reference
      * internal_agent: another LLM agent in this same network
    """
    tools_block: List[Dict[str, Any]] = config.get("tools") or []
    by_name: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for spec in tools_block:
        if not isinstance(spec, dict):
            continue
        name = (spec.get("function") or {}).get("name") or spec.get("name")
        if not isinstance(name, str):
            continue
        by_name[name] = spec
        order.append(name)
    if not order:
        return []

    front_man_name = order[0]
    front_man_spec = by_name[front_man_name]

    front_man_node: Dict[str, Any] = {
        "name": front_man_name,
        "kind": "front_man",
        "tools": [],
        "description": (front_man_spec.get("function") or {}).get("description") or "",
    }
    nodes: List[Dict[str, Any]] = [front_man_node]

    for tool_ref in front_man_spec.get("tools") or []:
        if isinstance(tool_ref, dict):
            # MCP tool ref — skip for now (out of scope for the demo viz).
            continue
        if not isinstance(tool_ref, str):
            continue

        # Cross-origin URL?
        if ExternalAgentParsing.is_external_agent(tool_ref):
            parsed = ExternalAgentParsing.parse_external_agent(tool_ref)
            child_name = (parsed or {}).get("agent_name") or tool_ref
            front_man_node["tools"].append(child_name)
            nodes.append({
                "name": child_name,
                "kind": "cross_origin",
                "url": tool_ref,
            })
            continue

        # Internal reference (by agent name within this network).
        child_spec = by_name.get(tool_ref)
        front_man_node["tools"].append(tool_ref)
        if child_spec is None:
            nodes.append({"name": tool_ref, "kind": "unknown"})
            continue

        if child_spec.get("client_side"):
            kind = "client_side"
        elif child_spec.get("class") or child_spec.get("toolbox"):
            kind = "coded_tool"
        else:
            kind = "internal_agent"
        nodes.append({
            "name": tool_ref,
            "kind": kind,
            "description": (child_spec.get("function") or {}).get("description") or "",
        })
    return nodes


# Default template used when AGENT_STATIC_DIR is not set (no chat UI bundled).
# This page still works — it shows the catalog of networks with clickable
# links. Clicking a link sends the user to the raw notebook JSON, which is
# enough for "view source" but not a chat experience.
_DEFAULT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Agent Web — {origin_host}</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; max-width: 720px;
                margin: 2rem auto; padding: 0 1rem; color: #1f1f23; }}
        h1 {{ font-size: 1.4rem; }}
        .origin {{ font-family: monospace; color: #2b6cb0; }}
        ul {{ list-style: none; padding: 0; }}
        li {{ padding: 0.8rem 1rem; border: 1px solid #e5e5e7;
              border-radius: 4px; margin: 0.5rem 0; }}
        li a {{ font-weight: 600; color: #2b6cb0; text-decoration: none; }}
        li .desc {{ display: block; color: #666; margin-top: 0.3rem; font-size: 0.9rem; }}
        .muted {{ color: #888; font-size: 0.85rem; }}
    </style>
</head>
<body>
    <h1>Agent Web</h1>
    <p>You are at origin <span class="origin">{origin}</span>.</p>
    <p>This origin publishes the following distributable agent networks:</p>
    {networks_html}
    <p class="muted">No chat UI is hosted at this origin. To browse these
       networks interactively, point an Agent Web browser runtime
       (e.g. the <code>neuro-san-lite</code> bundle) at one of the
       URLs above.</p>
</body>
</html>
"""


class LandingHandler(BaseRequestHandler):
    """HTML index page at GET / for this origin's distributable networks."""

    async def get(self):
        try:
            origin = self._derive_origin()
            networks = self._collect_distributable_networks(origin)
            html = self._render(origin, networks)
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write(html)
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            self.process_exception(exc)
        finally:
            self.do_finish()

    async def options(self, *_args, **_kwargs):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_status(HTTPStatus.NO_CONTENT)
        self.do_finish()

    # --- internals -------------------------------------------------------

    def _derive_origin(self) -> str:
        scheme = self.request.headers.get("X-Forwarded-Proto") or self.request.protocol
        host = self.request.headers.get("X-Forwarded-Host") or self.request.host
        return f"{scheme}://{host}"

    def _collect_distributable_networks(self, origin: str) -> List[Dict[str, Any]]:
        """Return [{name, description, url, tools, branding?}, ...] for each
        distributable network this origin publishes."""
        network_storage_dict: Dict[str, AgentNetworkStorage] = (
            self.server_context.get_network_storage_dict()
        )
        public_storage: AgentNetworkStorage = network_storage_dict.get(StorageClass.PUBLIC)
        if public_storage is None:
            return []

        out: List[Dict[str, Any]] = []
        # pylint: disable=protected-access
        for name, agent_network in public_storage.agents_table.items():
            if not isinstance(agent_network, AgentNetwork):
                continue
            if not agent_network.is_distributable():
                continue
            config = agent_network.get_config() or {}
            meta = config.get("metadata") or {}
            description = meta.get("description") or ""
            sample_queries = meta.get("sample_queries") or []
            entry: Dict[str, Any] = {
                "name": name,
                "description": description,
                "sample_queries": sample_queries,
                "url": f"{origin}/api/v1/{name}/network",
                "tools": _summarize_tool_graph(config),
            }
            branding = meta.get("branding")
            if isinstance(branding, dict):
                entry["branding"] = branding
            out.append(entry)
        # Stable order so the demo is deterministic.
        out.sort(key=lambda n: n["name"])
        return out

    def _pick_branding(self, networks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Pick the first network's branding block (if any) for the page's
        chrome. Multi-network origins use the first distributable network as
        the face."""
        for n in networks:
            b = n.get("branding")
            if isinstance(b, dict):
                return b
        return {}

    def _render(self, origin: str, networks: List[Dict[str, Any]]) -> str:
        """Return the rendered HTML.

        When AGENT_STATIC_DIR points at a directory containing index.html,
        we serve that file with a bootstrap <script> injected at the top of
        <head>. Otherwise we fall back to the simple default template above.
        """
        static_dir = os.environ.get("AGENT_STATIC_DIR")
        if static_dir:
            index_path = Path(static_dir) / "index.html"
            if index_path.is_file():
                try:
                    return self._render_with_bootstrap(
                        index_path.read_text(encoding="utf-8"),
                        origin,
                        networks,
                        branding=self._pick_branding(networks),
                    )
                # pylint: disable=broad-exception-caught
                except Exception:
                    # Fall back to default if we can't read the template.
                    pass
        return self._render_default(origin, networks)

    @staticmethod
    def _render_with_bootstrap(template_html: str,
                                origin: str,
                                networks: List[Dict[str, Any]],
                                branding: Dict[str, Any] | None = None) -> str:
        """Inject window.AGENT_WEB_BOOTSTRAP into the index.html template.
        When branding is present, also inject a <style> block that exposes
        each branding key as a CSS custom property under :root so the page
        can pick it up without any JS work."""
        bootstrap: Dict[str, Any] = {
            "origin": origin,
            "networks": networks,
        }
        if branding:
            bootstrap["branding"] = branding

        injected = (
            "<script>\n"
            f"window.AGENT_WEB_BOOTSTRAP = {json.dumps(bootstrap)};\n"
            "</script>\n"
        )
        if branding:
            css_vars = _branding_to_css_vars(branding)
            if css_vars:
                injected += "<style>\n:root {\n" + css_vars + "\n}\n</style>\n"

        # Insert before </head> if present, else prepend.
        lower = template_html.lower()
        head_close = lower.find("</head>")
        if head_close >= 0:
            return template_html[:head_close] + injected + template_html[head_close:]
        return injected + template_html

    @staticmethod
    def _render_default(origin: str, networks: List[Dict[str, Any]]) -> str:
        if not networks:
            networks_html = (
                "<p class=\"muted\">This origin has no distributable networks "
                "configured (set <code>distributable: true</code> on a "
                "manifest entry).</p>"
            )
        else:
            items: List[str] = []
            for net in networks:
                items.append(
                    "<li>"
                    f"<a href=\"{escape(net['url'])}\">{escape(net['name'])}</a>"
                    f"<span class=\"desc\">{escape(net.get('description') or '(no description)')}</span>"
                    "</li>"
                )
            networks_html = "<ul>" + "".join(items) + "</ul>"

        origin_host = escape(origin.replace("https://", "").replace("http://", ""))
        return _DEFAULT_TEMPLATE.format(
            origin=escape(origin),
            origin_host=origin_host,
            networks_html=networks_html,
        )
