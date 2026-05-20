
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
Wire-config: extract + verify the scrubbed JSON payload from an Agent Web
notebook before instantiating the network.

Mirror: neuro-san-lite-js/src/wire-config.ts
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Dict, List
from urllib.parse import urlparse


AGENT_NETWORK_MIMETYPE = "application/x-agent-network+json"
SUPPORTED_PROTOCOL_VERSION = "0.1"


class WireConfigError(ValueError):
    """Raised when a fetched notebook is malformed or fails a safety check."""


def extract_wire_config_from_notebook(notebook: Dict[str, Any]) -> Dict[str, Any]:
    """
    Locate the raw cell carrying the network spec inside an Agent Web notebook
    and parse it. The cell is identified by its metadata: either
    `agent_web_role == "network_spec"` or `format == application/x-agent-network+json`.

    :raises WireConfigError: if no such cell is found or the JSON is invalid.
    """
    if not isinstance(notebook, dict):
        raise WireConfigError(
            f"Notebook must be an object, got {type(notebook).__name__}"
        )
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        raise WireConfigError("Notebook has no 'cells' array")

    for cell in cells:
        if not isinstance(cell, dict):
            continue
        if cell.get("cell_type") != "raw":
            continue
        meta = cell.get("metadata", {}) or {}
        role = meta.get("agent_web_role")
        fmt = meta.get("format")
        if role == "network_spec" or fmt == AGENT_NETWORK_MIMETYPE:
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)
            if not isinstance(source, str):
                raise WireConfigError(
                    f"Spec cell 'source' must be string or list of strings, "
                    f"got {type(source).__name__}"
                )
            try:
                return json.loads(source)
            except json.JSONDecodeError as exc:
                raise WireConfigError(
                    f"Spec cell does not parse as JSON: {exc}"
                ) from exc

    raise WireConfigError(
        "No agent_web network_spec cell found in notebook. Is this an Agent "
        "Web notebook?"
    )


def verify_wire_config(wire: Dict[str, Any]) -> None:
    """
    Enforce browser-side invariants on a wire config:

      * `agent_web.protocol_version` matches what this client supports.
      * `agent_web.origin` is present and well-formed.
      * Every `coded_tool_url` on a tool is same-origin with `agent_web.origin`.
      * Every `client_side: true` tool carries `client_side_source` and `integrity`.
      * No leftover `class` or `toolbox` fields (the scrubber must strip them).

    Raises WireConfigError on any violation. Returns None on success.
    """
    if not isinstance(wire, dict):
        raise WireConfigError(
            f"Wire config must be an object, got {type(wire).__name__}"
        )

    meta = wire.get("agent_web") or {}
    if not isinstance(meta, dict):
        raise WireConfigError("agent_web metadata block is malformed")

    proto = meta.get("protocol_version")
    origin = meta.get("origin")
    if proto != SUPPORTED_PROTOCOL_VERSION:
        raise WireConfigError(
            f"Agent Web protocol version mismatch: notebook is {proto!r}, "
            f"runtime supports {SUPPORTED_PROTOCOL_VERSION!r}."
        )
    if not isinstance(origin, str) or not origin:
        raise WireConfigError(
            "Notebook missing agent_web.origin metadata; refusing to load."
        )

    origin_parsed = urlparse(origin)
    if not origin_parsed.scheme or not origin_parsed.netloc:
        raise WireConfigError(
            f"agent_web.origin is not a fully-qualified URL: {origin!r}"
        )
    origin_key = (origin_parsed.scheme, origin_parsed.netloc)

    tools = wire.get("tools") or []
    if not isinstance(tools, list):
        raise WireConfigError("wire 'tools' must be an array")

    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name") or "<unnamed>"
        if "class" in tool:
            raise WireConfigError(
                f"tool {name!r} still has 'class' in the wire form. "
                f"Origin's scrubber is misconfigured."
            )
        if "toolbox" in tool:
            raise WireConfigError(
                f"tool {name!r} still has 'toolbox' in the wire form."
            )

        coded_tool_url = tool.get("coded_tool_url")
        if coded_tool_url is not None:
            if not isinstance(coded_tool_url, str):
                raise WireConfigError(
                    f"tool {name!r}: coded_tool_url must be a string"
                )
            parsed = urlparse(coded_tool_url)
            if (parsed.scheme, parsed.netloc) != origin_key:
                raise WireConfigError(
                    f"tool {name!r}: coded_tool_url {coded_tool_url!r} is not "
                    f"same-origin with the notebook origin {origin!r}."
                )

        if tool.get("client_side"):
            if not tool.get("client_side_source"):
                raise WireConfigError(
                    f"tool {name!r}: client_side tool is missing "
                    f"client_side_source."
                )
            integrity = tool.get("integrity")
            if not isinstance(integrity, str) or not integrity.startswith("sha256-"):
                raise WireConfigError(
                    f"tool {name!r}: client_side tool is missing a valid "
                    f"sha256-* integrity hash."
                )


def verify_client_side_source_integrity(source_b64: str, integrity: str) -> bytes:
    """
    Verify a shipped client-side tool source matches its declared integrity hash
    and return the raw source bytes.

    :raises WireConfigError: on bad base64, missing/malformed integrity field,
            or hash mismatch.
    """
    if not isinstance(source_b64, str) or not source_b64:
        raise WireConfigError("client_side_source is empty or not a string")
    if not isinstance(integrity, str) or not integrity.startswith("sha256-"):
        raise WireConfigError(
            f"integrity must be a sha256-<hex> string, got {integrity!r}"
        )
    try:
        source_bytes = base64.b64decode(source_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise WireConfigError(f"bad base64 in client_side_source: {exc}") from exc

    expected = integrity[len("sha256-"):]
    actual = hashlib.sha256(source_bytes).hexdigest()
    if expected != actual:
        raise WireConfigError(
            f"integrity check failed: expected sha256-{expected}, "
            f"got sha256-{actual}"
        )
    return source_bytes


def get_origin(wire: Dict[str, Any]) -> str:
    """Convenience accessor — returns the origin url stamped by the scrubber."""
    meta = wire.get("agent_web") or {}
    return meta.get("origin", "")


def get_network_name(wire: Dict[str, Any]) -> str:
    """Convenience accessor — returns the network name stamped by the scrubber."""
    meta = wire.get("agent_web") or {}
    return meta.get("network_name", "")


def list_tool_names(wire: Dict[str, Any]) -> List[str]:
    """List the agent tool names declared in the wire form."""
    out: List[str] = []
    for tool in wire.get("tools") or []:
        if isinstance(tool, dict):
            name = tool.get("name")
            if isinstance(name, str):
                out.append(name)
    return out
