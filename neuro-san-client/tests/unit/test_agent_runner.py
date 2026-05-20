
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
"""Unit tests for neuro_san_client.agent_runner.

We use httpx.MockTransport to deterministically simulate the origin server
without spawning any real HTTP. Tests cover request shape (BYOK threading),
event-stream parsing, and error handling.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import httpx
import pytest

from neuro_san_client.agent_runner import (
    ChatEvent,
    RunnerOptions,
    RunnerResult,
    _build_request,
    _derive_streaming_chat_url,
    fetch_notebook,
    run_agent_turn,
)
from neuro_san_client.wire_config import AGENT_NETWORK_MIMETYPE, SUPPORTED_PROTOCOL_VERSION


# ---------- fixtures ----------


def _minimal_wire(origin: str = "http://origin.example:8801",
                   network_name: str = "flight_finder") -> Dict[str, Any]:
    return {
        "agent_web": {
            "protocol_version": SUPPORTED_PROTOCOL_VERSION,
            "origin": origin,
            "network_name": network_name,
        },
        "llm_config": {"model_name": "claude-haiku"},
        "tools": [],
    }


def _notebook(spec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "nbformat": 4,
        "metadata": {},
        "cells": [
            {
                "cell_type": "raw",
                "metadata": {
                    "format": AGENT_NETWORK_MIMETYPE,
                    "agent_web_role": "network_spec",
                },
                "source": json.dumps(spec),
            }
        ],
    }


def _streaming_chunk(text: str, msg_type: str = "AI",
                       chat_context: Any = None,
                       sly_data: Any = None,
                       structure: Any = None) -> str:
    """Encode one chunk in the JSON-lines format the origin emits."""
    response: Dict[str, Any] = {"type": msg_type, "text": text}
    if chat_context is not None:
        response["chat_context"] = chat_context
    if sly_data is not None:
        response["sly_data"] = sly_data
    if structure is not None:
        response["structure"] = structure
    return json.dumps({"response": response}) + "\n"


# ---------- _derive_streaming_chat_url ----------


class TestDeriveStreamingChatUrl:
    def test_simple_http(self):
        u = _derive_streaming_chat_url(
            "http://origin.example:8801/api/v1/foo/network", "foo"
        )
        assert u == "http://origin.example:8801/api/v1/foo/streaming_chat"

    def test_https(self):
        u = _derive_streaming_chat_url(
            "https://api.example/api/v1/bar/network", "bar"
        )
        assert u == "https://api.example/api/v1/bar/streaming_chat"

    def test_origin_takes_precedence_over_path_shape(self):
        # Even if someone gave us a weirdly-shaped path, the origin is what
        # we trust.
        u = _derive_streaming_chat_url(
            "http://origin.example/anything", "x"
        )
        assert u.startswith("http://origin.example/api/v1/x/")

    def test_bad_url_raises(self):
        with pytest.raises(ValueError, match="not fully qualified"):
            _derive_streaming_chat_url("/just/a/path", "foo")


# ---------- _build_request (BYOK threading) ----------


class TestBuildRequest:
    def test_minimal_request_has_user_message_and_maximal_filter(self):
        opts = RunnerOptions(url="x", message="hi")
        body = _build_request(opts)
        assert body == {
            "user_message": {"type": "HUMAN", "text": "hi"},
            "chat_filter": {"chat_filter_type": "MAXIMAL"},
        }

    def test_anthropic_key_lands_in_sly_data_llm_config(self):
        opts = RunnerOptions(url="x", message="hi", anthropic_key="sk-ant-foo")
        body = _build_request(opts)
        assert body["sly_data"]["llm_config"]["api_key"] == "sk-ant-foo"
        assert body["sly_data"]["llm_config"]["anthropic_api_key"] == "sk-ant-foo"

    def test_openai_key_lands_in_sly_data_llm_config(self):
        opts = RunnerOptions(url="x", message="hi", openai_key="sk-openai-bar")
        body = _build_request(opts)
        # Without an anthropic key set, api_key falls to openai's value.
        assert body["sly_data"]["llm_config"]["api_key"] == "sk-openai-bar"
        assert body["sly_data"]["llm_config"]["openai_api_key"] == "sk-openai-bar"

    def test_both_keys_send_both_provider_specific(self):
        opts = RunnerOptions(url="x", message="hi",
                              anthropic_key="sk-a", openai_key="sk-o")
        body = _build_request(opts)
        cfg = body["sly_data"]["llm_config"]
        # api_key defaults to anthropic (set first)
        assert cfg["api_key"] == "sk-a"
        assert cfg["anthropic_api_key"] == "sk-a"
        assert cfg["openai_api_key"] == "sk-o"

    def test_caller_supplied_sly_data_is_preserved(self):
        opts = RunnerOptions(url="x", message="hi",
                              sly_data={"passenger_email": "bob@example.com"},
                              anthropic_key="sk-ant-foo")
        body = _build_request(opts)
        assert body["sly_data"]["passenger_email"] == "bob@example.com"
        assert body["sly_data"]["llm_config"]["api_key"] == "sk-ant-foo"

    def test_caller_supplied_llm_config_takes_precedence(self):
        opts = RunnerOptions(
            url="x", message="hi",
            sly_data={"llm_config": {"api_key": "explicitly-set"}},
            anthropic_key="sk-ant-foo",
        )
        body = _build_request(opts)
        # The explicitly-set value wins (setdefault behavior).
        assert body["sly_data"]["llm_config"]["api_key"] == "explicitly-set"
        # But provider-specific fields still get added.
        assert body["sly_data"]["llm_config"]["anthropic_api_key"] == "sk-ant-foo"

    def test_chat_context_threaded_in(self):
        opts = RunnerOptions(url="x", message="hi",
                              chat_context={"history": ["..."]})
        body = _build_request(opts)
        assert body["chat_context"] == {"history": ["..."]}

    def test_empty_chat_context_omitted(self):
        opts = RunnerOptions(url="x", message="hi", chat_context={})
        body = _build_request(opts)
        assert "chat_context" not in body

    def test_no_mutation_of_caller_sly_data(self):
        caller_sly = {"passenger_email": "bob@example.com"}
        opts = RunnerOptions(url="x", message="hi",
                              sly_data=caller_sly,
                              anthropic_key="sk-ant-foo")
        _build_request(opts)
        # The caller's dict must not have been mutated.
        assert caller_sly == {"passenger_email": "bob@example.com"}


# ---------- fetch_notebook ----------


class TestFetchNotebook:
    @pytest.mark.asyncio
    async def test_fetches_and_parses(self):
        wire = _minimal_wire()
        nb = _notebook(wire)
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json=nb)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            out = await fetch_notebook("http://x/network", client=client)
        assert out == nb

    @pytest.mark.asyncio
    async def test_raises_on_404(self):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(404, text="nope")
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_notebook("http://x/network", client=client)


# ---------- run_agent_turn full streaming flow ----------


class _MockOrigin:
    """Helper: builds an httpx.MockTransport that serves both /network
    and a deterministic /streaming_chat stream."""

    def __init__(self, wire: Dict[str, Any], chunks: List[str]):
        self.wire = wire
        self.chunks = chunks
        self.recorded_streaming_request_body: bytes = b""
        self.recorded_streaming_url: str = ""

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/network"):
            return httpx.Response(200, json=_notebook(self.wire))
        if path.endswith("/streaming_chat"):
            self.recorded_streaming_request_body = request.content
            self.recorded_streaming_url = str(request.url)
            joined = "".join(self.chunks)
            return httpx.Response(200, content=joined.encode("utf-8"))
        return httpx.Response(404, text=f"unhandled path: {path}")

    def make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


class TestRunAgentTurn:
    @pytest.mark.asyncio
    async def test_minimal_successful_turn(self):
        wire = _minimal_wire(origin="http://origin.example",
                              network_name="trip_planner")
        chunks = [
            _streaming_chunk("Hello, how can I help?", msg_type="AGENT_FRAMEWORK"),
            _streaming_chunk("", msg_type="AGENT_FRAMEWORK",
                             chat_context={"history": ["..."]},
                             sly_data={"last_booking_code": "HOLD-XYZ"}),
        ]
        mock = _MockOrigin(wire, chunks)
        opts = RunnerOptions(
            url="http://origin.example/api/v1/trip_planner/network",
            message="hi", anthropic_key="sk-ant-foo",
        )

        events: List[ChatEvent] = []
        async with mock.make_client() as client:
            async for event in run_agent_turn(opts, client=client):
                events.append(event)

        kinds = [e.kind for e in events]
        assert "network" in kinds
        assert "agent" in kinds
        assert kinds[-1] == "done"

        # The final "done" event carries the RunnerResult.
        result = events[-1].payload
        assert isinstance(result, RunnerResult)
        assert result.answer == "Hello, how can I help?"
        assert result.chat_context == {"history": ["..."]}
        assert result.sly_data["last_booking_code"] == "HOLD-XYZ"

    @pytest.mark.asyncio
    async def test_byok_key_is_threaded_into_request_body(self):
        wire = _minimal_wire()
        chunks = [_streaming_chunk("hi", msg_type="AGENT_FRAMEWORK")]
        mock = _MockOrigin(wire, chunks)
        opts = RunnerOptions(url="http://origin.example:8801/api/v1/flight_finder/network",
                              message="hi", anthropic_key="sk-ant-the-key")

        async with mock.make_client() as client:
            async for _ in run_agent_turn(opts, client=client):
                pass

        body = json.loads(mock.recorded_streaming_request_body.decode("utf-8"))
        assert body["sly_data"]["llm_config"]["api_key"] == "sk-ant-the-key"
        assert body["user_message"]["text"] == "hi"

    @pytest.mark.asyncio
    async def test_streaming_url_uses_wire_config_origin(self):
        # The URL we actually POST to is derived from the network URL host,
        # not the random path. Confirms we don't get redirected off-origin.
        wire = _minimal_wire(origin="http://origin.example:8801",
                              network_name="flight_finder")
        chunks = [_streaming_chunk("hi", msg_type="AGENT_FRAMEWORK")]
        mock = _MockOrigin(wire, chunks)
        opts = RunnerOptions(
            url="http://origin.example:8801/api/v1/flight_finder/network",
            message="hi", anthropic_key="k",
        )

        async with mock.make_client() as client:
            async for _ in run_agent_turn(opts, client=client):
                pass

        assert mock.recorded_streaming_url == (
            "http://origin.example:8801/api/v1/flight_finder/streaming_chat"
        )

    @pytest.mark.asyncio
    async def test_404_notebook_yields_error(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = []
            opts = RunnerOptions(url="http://x/network", message="hi")
            async for ev in run_agent_turn(opts, client=client):
                events.append(ev)
        kinds = [e.kind for e in events]
        assert "error" in kinds
        assert kinds[-1] == "done"

    @pytest.mark.asyncio
    async def test_bad_protocol_version_yields_error(self):
        wire = _minimal_wire()
        wire["agent_web"]["protocol_version"] = "9.9"
        chunks: list = []
        mock = _MockOrigin(wire, chunks)
        opts = RunnerOptions(url="http://x/api/v1/x/network", message="hi")

        events = []
        async with mock.make_client() as client:
            async for ev in run_agent_turn(opts, client=client):
                events.append(ev)
        kinds = [e.kind for e in events]
        assert "error" in kinds
        err_payload = [e.payload for e in events if e.kind == "error"][0]
        assert "Wire config invalid" in err_payload

    @pytest.mark.asyncio
    async def test_streaming_500_yields_error(self):
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/network"):
                return httpx.Response(200, json=_notebook(_minimal_wire()))
            return httpx.Response(500, text="internal")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = []
            opts = RunnerOptions(
                url="http://origin.example:8801/api/v1/flight_finder/network",
                message="hi",
            )
            async for ev in run_agent_turn(opts, client=client):
                events.append(ev)
        kinds = [e.kind for e in events]
        assert "error" in kinds
        assert kinds[-1] == "done"

    @pytest.mark.asyncio
    async def test_thinking_messages_surface_separately(self):
        wire = _minimal_wire()
        chunks = [
            _streaming_chunk("about to call tool", msg_type="AGENT"),
            _streaming_chunk("progress msg", msg_type="AGENT_PROGRESS"),
            _streaming_chunk("tool result", msg_type="AGENT_TOOL_RESULT"),
            _streaming_chunk("final answer", msg_type="AGENT_FRAMEWORK"),
        ]
        mock = _MockOrigin(wire, chunks)
        opts = RunnerOptions(
            url="http://origin.example:8801/api/v1/flight_finder/network",
            message="hi",
        )
        events = []
        async with mock.make_client() as client:
            async for ev in run_agent_turn(opts, client=client):
                events.append(ev)
        kinds = [e.kind for e in events]
        thinking_count = sum(1 for k in kinds if k == "thinking")
        assert thinking_count == 3, (
            "AGENT, AGENT_PROGRESS, AGENT_TOOL_RESULT should all be 'thinking'"
        )
        assert "agent" in kinds
        result = events[-1].payload
        assert result.answer == "final answer"

    @pytest.mark.asyncio
    async def test_server_side_network_call_surfaces_as_network_event(self):
        """A chunk whose structure.network_call is set should yield a
        ChatEvent("network", ...) regardless of msg_type — that's how the
        browser learns about cross-origin calls travelgenius made on its behalf."""
        wire = _minimal_wire()
        chunks = [
            # ExternalActivation start emits this BEFORE making the call.
            _streaming_chunk(
                "Calling flight_finder",
                msg_type="AGENT",
                structure={
                    "tool_start": True,
                    "network_call": {
                        "kind": "streaming_chat",
                        "method": "POST",
                        "url": "http://flights.example/flight_finder",
                        "status": None,
                    },
                },
            ),
            # ExternalActivation end emits this AFTER the call completes.
            _streaming_chunk(
                "Got result",
                msg_type="AGENT",
                structure={
                    "tool_end": True,
                    "network_call": {
                        "kind": "streaming_chat",
                        "method": "POST",
                        "url": "http://flights.example/flight_finder",
                        "status": 200,
                        "ms": 1234,
                    },
                },
            ),
            _streaming_chunk("final answer", msg_type="AGENT_FRAMEWORK"),
        ]
        mock = _MockOrigin(wire, chunks)
        opts = RunnerOptions(
            url="http://origin.example:8801/api/v1/flight_finder/network",
            message="hi",
        )
        events = []
        async with mock.make_client() as client:
            async for ev in run_agent_turn(opts, client=client):
                events.append(ev)
        net_events = [e for e in events if e.kind == "network"]
        # Browser-direct network calls + 2 from structure (start & end)
        assert len(net_events) >= 2
        # Confirm the server-reported ones carry the right metadata.
        server_reported = [e for e in net_events
                            if isinstance(e.payload, dict)
                            and e.payload.get("url", "").startswith("http://flights.example")]
        assert len(server_reported) == 2
        # The "end" event should have a status and duration.
        ends = [e for e in server_reported if e.payload.get("status") == 200]
        assert len(ends) == 1
        assert ends[0].payload["ms"] == 1234
        # And the `via` annotation should mark which upstream stream it came from.
        for e in server_reported:
            assert e.payload["via"] == opts.url

    @pytest.mark.asyncio
    async def test_legacy_ai_message_type_still_treated_as_final(self):
        wire = _minimal_wire()
        chunks = [_streaming_chunk("legacy AI text", msg_type="AI")]
        mock = _MockOrigin(wire, chunks)
        opts = RunnerOptions(
            url="http://origin.example:8801/api/v1/flight_finder/network",
            message="hi",
        )
        events = []
        async with mock.make_client() as client:
            async for ev in run_agent_turn(opts, client=client):
                events.append(ev)
        result = events[-1].payload
        assert result.answer == "legacy AI text"

    @pytest.mark.asyncio
    async def test_empty_lines_in_stream_are_ignored(self):
        wire = _minimal_wire()
        chunks = ["\n", _streaming_chunk("hi", msg_type="AGENT_FRAMEWORK"), "\n"]
        mock = _MockOrigin(wire, chunks)
        opts = RunnerOptions(
            url="http://origin.example:8801/api/v1/flight_finder/network",
            message="hi",
        )
        events = []
        async with mock.make_client() as client:
            async for ev in run_agent_turn(opts, client=client):
                events.append(ev)
        result = events[-1].payload
        assert result.answer == "hi"

    @pytest.mark.asyncio
    async def test_malformed_json_line_is_skipped(self):
        wire = _minimal_wire()
        chunks = ["not valid json\n", _streaming_chunk("ok", msg_type="AGENT_FRAMEWORK")]
        mock = _MockOrigin(wire, chunks)
        opts = RunnerOptions(
            url="http://origin.example:8801/api/v1/flight_finder/network",
            message="hi",
        )
        events = []
        async with mock.make_client() as client:
            async for ev in run_agent_turn(opts, client=client):
                events.append(ev)
        result = events[-1].payload
        assert result.answer == "ok"
