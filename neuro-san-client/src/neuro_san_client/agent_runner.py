
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
agent_runner: the BYOK chat-loop driver used by both the Python and TS clients.

For the MVP, this delegates orchestration to the **origin's** /streaming_chat
endpoint. The client supplies LLM credentials via `sly_data.llm_config`; the
origin uses them per-request without persisting. This means:

    - the client doesn't need a JS/Python LLM SDK,
    - cross-origin agents resolve at the origin via existing ExternalActivation,
    - client-side coded tools (`client_side_source`) are NOT exercised in this
      MVP path (the origin runs everything). Adding them is a follow-up.

Mirror: neuro-san-lite-js/src/agent_runner.ts
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Optional
from urllib.parse import urlparse

import httpx

from . import wire_config


@dataclass
class ChatEvent:
    """One event from the chat stream, surfaced to the UI."""

    kind: str    # "user" | "agent" | "thinking" | "network" | "error" | "done"
    payload: Any


@dataclass
class RunnerOptions:
    """Per-turn options."""

    url: str
    message: str
    anthropic_key: str = ""
    openai_key: str = ""
    chat_context: Dict[str, Any] = field(default_factory=dict)
    sly_data: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 180.0


@dataclass
class RunnerResult:
    """Final state at the end of a turn — useful for the caller to thread back in."""

    chat_context: Dict[str, Any] = field(default_factory=dict)
    sly_data: Dict[str, Any] = field(default_factory=dict)
    answer: str = ""


# ---------------------------------------------------------------------------
# Internals: small helpers shared by the streaming runner.
# ---------------------------------------------------------------------------


def _derive_streaming_chat_url(network_url: str, network_name: str) -> str:
    """
    Given a notebook URL like https://host/api/v1/{name}/network, derive the
    matching /streaming_chat endpoint. We use the wire-config-stamped origin
    so a misleadingly-shaped network_url cannot redirect us off-origin.
    """
    parsed = urlparse(network_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"network_url is not fully qualified: {network_url!r}")
    return f"{parsed.scheme}://{parsed.netloc}/api/v1/{network_name}/streaming_chat"


def _build_request(opts: RunnerOptions) -> Dict[str, Any]:
    """Build the streaming_chat request body, threading the BYOK keys into
    sly_data.llm_config."""
    sly_data: Dict[str, Any] = dict(opts.sly_data or {})

    # Thread BYOK keys into sly_data.llm_config so the server's
    # replace_any_required_api_keys() picks them up.
    llm_keys: Dict[str, Any] = dict(sly_data.get("llm_config") or {})
    if opts.anthropic_key:
        llm_keys.setdefault("api_key", opts.anthropic_key)
        llm_keys["anthropic_api_key"] = opts.anthropic_key
    if opts.openai_key:
        llm_keys.setdefault("api_key", opts.openai_key)
        llm_keys["openai_api_key"] = opts.openai_key
    if llm_keys:
        sly_data["llm_config"] = llm_keys

    request: Dict[str, Any] = {
        "user_message": {"type": "HUMAN", "text": opts.message},
        # MAXIMAL: pass intermediate AGENT messages too (default MINIMAL
        # drops them). We need them for the network_call events that
        # ExternalActivation embeds in the stream — without them, the
        # browser can't render cross-origin choreography in its trace panel.
        "chat_filter": {"chat_filter_type": "MAXIMAL"},
    }
    if opts.chat_context:
        request["chat_context"] = opts.chat_context
    if sly_data:
        request["sly_data"] = sly_data
    return request


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


async def fetch_notebook(url: str,
                          client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """Fetch and JSON-decode the Agent Web notebook at `url`.

    Tests inject an httpx.AsyncClient backed by httpx.MockTransport.
    """
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns_client:
            await client.aclose()


async def run_agent_turn(opts: RunnerOptions,
                          client: Optional[httpx.AsyncClient] = None
                          ) -> AsyncIterator[ChatEvent]:
    """
    Drive one chat turn.

    Yields ChatEvent objects as the conversation streams. The final event is
    always a ChatEvent("done", RunnerResult).

    Tests inject a client that uses httpx.MockTransport for deterministic
    network behavior.
    """
    async for event in _run_agent_turn_impl(opts, client):
        yield event


async def _run_agent_turn_impl(opts: RunnerOptions,
                                client: Optional[httpx.AsyncClient]
                                ) -> AsyncIterator[ChatEvent]:
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=opts.timeout_seconds)
    result = RunnerResult(
        chat_context=dict(opts.chat_context or {}),
        sly_data=dict(opts.sly_data or {}),
    )

    try:
        # 1) Fetch notebook.
        yield ChatEvent("network", {"kind": "notebook", "method": "GET",
                                     "url": opts.url, "status": None})
        try:
            resp = await client.get(opts.url)
        except httpx.HTTPError as exc:
            yield ChatEvent("error", f"Notebook fetch failed: {exc}")
            yield ChatEvent("done", result)
            return
        if resp.status_code != 200:
            yield ChatEvent("error",
                            f"Notebook GET {opts.url} returned HTTP {resp.status_code}")
            yield ChatEvent("done", result)
            return
        yield ChatEvent("network", {"kind": "notebook", "method": "GET",
                                     "url": opts.url, "status": resp.status_code})
        notebook = resp.json()

        # 2) Extract + verify wire config.
        try:
            wire = wire_config.extract_wire_config_from_notebook(notebook)
            wire_config.verify_wire_config(wire)
        except wire_config.WireConfigError as exc:
            yield ChatEvent("error", f"Wire config invalid: {exc}")
            yield ChatEvent("done", result)
            return

        # 3) Stream the chat against the origin.
        network_name = wire_config.get_network_name(wire)
        streaming_url = _derive_streaming_chat_url(opts.url, network_name)
        request_body = _build_request(opts)

        yield ChatEvent("network", {"kind": "streaming_chat", "method": "POST",
                                     "url": streaming_url, "status": None})

        compiled_parts: list = []

        try:
            async with client.stream(
                "POST", streaming_url,
                content=json.dumps(request_body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            ) as stream_resp:
                if stream_resp.status_code != 200:
                    body = await stream_resp.aread()
                    yield ChatEvent(
                        "error",
                        f"streaming_chat HTTP {stream_resp.status_code}: "
                        f"{body[:300]!r}"
                    )
                    yield ChatEvent("done", result)
                    return
                yield ChatEvent("network", {"kind": "streaming_chat",
                                             "method": "POST", "url": streaming_url,
                                             "status": stream_resp.status_code})

                async for line in stream_resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    response = chunk.get("response") or {}
                    msg_type = response.get("type")
                    text = response.get("text")
                    chat_ctx = response.get("chat_context")
                    sly = response.get("sly_data")
                    structure = response.get("structure") or {}
                    if chat_ctx:
                        result.chat_context = chat_ctx
                    if sly:
                        result.sly_data.update(sly)
                    # Server-side cross-origin calls (made by ExternalActivation
                    # or RemoteToolActivation upstream of us) embed a
                    # `network_call` field in the message's structure. Surface
                    # those as network events so a runtime's trace panel can
                    # render the choreography the origin executed on the
                    # caller's behalf.
                    net_call = structure.get("network_call") if isinstance(structure, dict) else None
                    if net_call:
                        # Mark which origin reported the call so the UI can
                        # distinguish browser-direct calls from server-reported
                        # ones.
                        annotated = dict(net_call)
                        annotated.setdefault("via", opts.url)
                        yield ChatEvent("network", annotated)
                    # AGENT_FRAMEWORK carries the front man's final user-facing
                    # answer; AI is direct LLM output (usually filtered out by
                    # default chat_filter); AGENT / AGENT_PROGRESS /
                    # AGENT_TOOL_RESULT are intermediate "thinking" steps.
                    if msg_type in ("AGENT_FRAMEWORK", "AI") and text:
                        compiled_parts.append(text)
                        yield ChatEvent("agent", text)
                    elif msg_type in ("AGENT", "AGENT_PROGRESS",
                                       "AGENT_TOOL_RESULT") and text:
                        yield ChatEvent("thinking", text)
        except httpx.HTTPError as exc:
            yield ChatEvent("error", f"streaming_chat failed: {exc}")
            yield ChatEvent("done", result)
            return

        result.answer = "".join(compiled_parts)
        yield ChatEvent("done", result)
    finally:
        if owns_client:
            await client.aclose()
