
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
from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler


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
        """Return [{name, description, url}, ...] for each distributable
        network this origin publishes."""
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
            out.append({
                "name": name,
                "description": description,
                "sample_queries": sample_queries,
                "url": f"{origin}/api/v1/{name}/network",
            })
        # Stable order so the demo is deterministic.
        out.sort(key=lambda n: n["name"])
        return out

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
                    )
                # pylint: disable=broad-exception-caught
                except Exception:
                    # Fall back to default if we can't read the template.
                    pass
        return self._render_default(origin, networks)

    @staticmethod
    def _render_with_bootstrap(template_html: str,
                                origin: str,
                                networks: List[Dict[str, Any]]) -> str:
        """Inject window.AGENT_WEB_BOOTSTRAP into the index.html template."""
        bootstrap = {
            "origin": origin,
            "networks": networks,
        }
        script = (
            "<script>\n"
            f"window.AGENT_WEB_BOOTSTRAP = {json.dumps(bootstrap)};\n"
            "</script>\n"
        )
        # Insert before </head> if present, else prepend.
        lower = template_html.lower()
        head_close = lower.find("</head>")
        if head_close >= 0:
            return template_html[:head_close] + script + template_html[head_close:]
        return script + template_html

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
