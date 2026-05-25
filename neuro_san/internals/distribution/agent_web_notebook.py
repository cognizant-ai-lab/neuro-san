
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
Build a Jupyter notebook (`.ipynb`) document around a scrubbed Agent Web wire
config so a runtime ("browser") can fetch one URL and have everything it needs
to instantiate the network.

See docs/agent_web_design.md (§6) for the cell layout specification.
"""
import json
from typing import Any
from typing import Dict
from typing import List


# Mimetype used for the raw cell that carries the wire config.
AGENT_NETWORK_MIMETYPE: str = "application/x-agent-network+json"


def build_agent_web_notebook(wire_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a notebook document around a scrubbed wire config.

    :param wire_config: The output of PublishedNetworkScrubber.scrub().
    :return: A dict in nbformat 4.5 layout, suitable for json.dumps().
    """
    meta = wire_config.get("agent_web", {}) or {}
    network_name: str = meta.get("network_name", "<unknown>")
    origin: str = meta.get("origin", "<unknown>")

    # Build the disclosure footer enumerating which tools run where.
    server_tools: List[str] = []
    client_tools: List[str] = []
    for agent_spec in wire_config.get("tools", []) or []:
        name = agent_spec.get("name") or (
            agent_spec.get("function", {}) or {}
        ).get("name", "<unnamed>")
        if agent_spec.get("client_side"):
            client_tools.append(name)
        elif "coded_tool_url" in agent_spec:
            server_tools.append(name)

    cells: List[Dict[str, Any]] = [
        _markdown_cell(
            f"# {network_name}\n\n"
            f"Served from `{origin}`.\n\n"
            f"This is an **Agent Web** published network. The cell below "
            f"will fetch the agent spec from this notebook, build the agent "
            f"locally in your runtime, and start a chat. Your LLM API key is "
            f"used for all model calls — the origin server never sees it."
        ),
        _raw_cell(
            mimetype=AGENT_NETWORK_MIMETYPE,
            body=json.dumps(wire_config, indent=2, sort_keys=False),
        ),
        _code_cell(
            "from neuro_san.client.agent_web_browser import open_agent_from_notebook\n"
            "open_agent_from_notebook()\n"
        ),
        _markdown_cell(
            _build_footer(meta, server_tools, client_tools)
        ),
    ]

    notebook: Dict[str, Any] = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "name": "python3",
                "display_name": "Python 3",
                "language": "python",
            },
            "language_info": {"name": "python"},
            "agent_web": meta,
        },
        "cells": cells,
    }
    return notebook


def _build_footer(meta: Dict[str, Any],
                  server_tools: List[str],
                  client_tools: List[str]) -> str:
    """Disclosure footer markdown."""
    lines: List[str] = ["---", "**Agent Web disclosure**", ""]
    lines.append(f"- Protocol version: `{meta.get('protocol_version', '?')}`")
    lines.append(f"- Origin: `{meta.get('origin', '?')}`")
    lines.append(f"- Published at: `{meta.get('published_at', '?')}`")
    lines.append("")
    if server_tools:
        lines.append("**Server-side tools (run on the origin):**")
        for tool in server_tools:
            lines.append(f"- `{tool}`")
    if client_tools:
        lines.append("")
        lines.append("**Client-side tools (run locally in your runtime):**")
        for tool in client_tools:
            lines.append(f"- `{tool}`")
    return "\n".join(lines)


def _markdown_cell(text: str) -> Dict[str, Any]:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": _split_lines(text),
    }


def _raw_cell(mimetype: str, body: str) -> Dict[str, Any]:
    return {
        "cell_type": "raw",
        "metadata": {
            "format": mimetype,
            "agent_web_role": "network_spec",
        },
        "source": _split_lines(body),
    }


def _code_cell(text: str) -> Dict[str, Any]:
    return {
        "cell_type": "code",
        "metadata": {"agent_web_role": "kickoff"},
        "source": _split_lines(text),
        "outputs": [],
        "execution_count": None,
    }


def _split_lines(text: str) -> List[str]:
    """nbformat stores cell source as a list of lines, each except the last
    keeping its trailing newline."""
    if not text:
        return []
    parts = text.splitlines(keepends=True)
    return parts


def extract_wire_config_from_notebook(notebook: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inverse helper: find the raw cell carrying the wire config and parse it.

    Used by the runtime's open_agent_from_notebook() helper.
    """
    for cell in notebook.get("cells", []) or []:
        if cell.get("cell_type") != "raw":
            continue
        cell_meta = cell.get("metadata", {}) or {}
        role = cell_meta.get("agent_web_role")
        fmt = cell_meta.get("format")
        if role == "network_spec" or fmt == AGENT_NETWORK_MIMETYPE:
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)
            return json.loads(source)
    raise ValueError(
        "No agent_web network_spec cell found in notebook. Is this an Agent Web notebook?"
    )
