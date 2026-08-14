
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
Unit and in-process integration tests for the record/playback LLM proxy.

The integration tests spin up an in-process fake "upstream" Tornado app plus the
real proxy application on ephemeral loopback ports, so they need neither a real
LLM host nor a running neuro-san server. They run as part of the default unit
suite.
"""
# Fixture parameters intentionally share the fixture's name (standard pytest).
# pylint: disable=redefined-outer-name
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

import json
import os

import pytest

import tornado.httpclient
import tornado.httpserver
import tornado.web

from tornado.testing import bind_unused_port

from tests.record_playback_llm_server.cassette import Cassette
from tests.record_playback_llm_server.cleanup_cassette import CassetteCleaner
from tests.record_playback_llm_server.playback_delay import PlaybackDelay
from tests.record_playback_llm_server.proxy_state import ProxyState
from tests.record_playback_llm_server.record_playback_llm_server import RecordPlaybackLlmServer
from tests.record_playback_llm_server.request_canonicalizer import RequestCanonicalizer
from tests.record_playback_llm_server.upstream_client import UpstreamClient


CHAT_PATH: str = "/v1/chat/completions"
PAYLOAD: Dict[str, Any] = {"model": "m", "messages": [{"role": "user", "content": "hey"}]}


class _CountingUpstream(tornado.web.RequestHandler):
    """Fake OpenAI upstream returning a distinct body ("resp-N") per call."""

    def initialize(self, box: Dict[str, int]) -> None:
        """Receive a shared call-counter box from the application."""
        # pylint: disable=attribute-defined-outside-init
        self.box = box

    def data_received(self, chunk):
        """Unused; the full body arrives via self.request.body."""
        return

    async def post(self) -> None:
        """Return a one-shot completion whose content increments each call."""
        self.box["n"] += 1
        self.write({
            "id": "chatcmpl-fake", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": f"resp-{self.box['n']}"},
                         "finish_reason": "stop"}],
        })


class _StreamUpstream(tornado.web.RequestHandler):
    """Fake OpenAI upstream that emits a short SSE stream."""

    def initialize(self, box: Dict[str, int]) -> None:
        """Receive a shared call-counter box from the application."""
        # pylint: disable=attribute-defined-outside-init
        self.box = box

    def data_received(self, chunk):
        """Unused; the full body arrives via self.request.body."""
        return

    async def post(self) -> None:
        """Stream three content tokens as SSE, then a [DONE] terminator."""
        self.box["n"] += 1
        self.set_header("Content-Type", "text/event-stream")
        for token in ["Hello", " from", " upstream"]:
            self.write(f'data: {json.dumps({"choices": [{"delta": {"content": token}}]})}\n\n')
            await self.flush()
        self.write("data: [DONE]\n\n")
        await self.flush()


class _RateLimitedUpstream(tornado.web.RequestHandler):
    """Fake OpenAI upstream that always rate-limits with HTTP 429."""

    def data_received(self, chunk):
        """Unused; the full body arrives via self.request.body."""
        return

    async def post(self) -> None:
        """Always respond 429 Too Many Requests."""
        self.set_status(429)
        self.write({"error": {"message": "Too Many Requests"}})


@pytest.fixture
def start_app():
    """
    Return a factory that binds a Tornado app to an unused loopback port and
    returns its base URL; all started servers are stopped on teardown.
    """
    servers: List[tornado.httpserver.HTTPServer] = []

    def _start(app: tornado.web.Application) -> str:
        sock, port = bind_unused_port()
        server = tornado.httpserver.HTTPServer(app)
        server.add_socket(sock)
        servers.append(server)
        return f"http://127.0.0.1:{port}"

    try:
        yield _start
    finally:
        for server in servers:
            server.stop()


async def _post(url: str, payload: Dict[str, Any], stream: bool = False) -> Tuple[int, bytes]:
    """POST JSON to url; when stream=True, accumulate and return the streamed body."""
    client = tornado.httpclient.AsyncHTTPClient(force_instance=True)
    body: Dict[str, Any] = {**payload, "stream": True} if stream else payload
    chunks = bytearray()
    response = await client.fetch(
        url, method="POST", body=json.dumps(body),
        headers={"Content-Type": "application/json"},
        streaming_callback=(chunks.extend if stream else None),
        request_timeout=30, raise_error=False)
    return response.code, (bytes(chunks) if stream else response.body)


def _content(body: bytes) -> str:
    """Extract the assistant text from a one-shot chat completion body."""
    return json.loads(body)["choices"][0]["message"]["content"]


def _upstream_client(base_url: str) -> UpstreamClient:
    """Build an UpstreamClient pointed at a fake upstream's /v1 base."""
    return UpstreamClient(base_url=f"{base_url}/v1", api_key=None)


class TestRequestCanonicalizer:
    """Canonical-key stability guarantees the record/playback matching relies on."""

    def test_key_ignores_json_key_order(self):
        """Requests differing only in JSON key order hash to the same key."""
        body_a = json.dumps({"model": "m", "stream": False, "messages": []}).encode()
        body_b = json.dumps({"messages": [], "stream": False, "model": "m"}).encode()
        assert RequestCanonicalizer.key("POST", CHAT_PATH, body_a) == \
            RequestCanonicalizer.key("POST", CHAT_PATH, body_b)

    def test_stream_flag_changes_key(self):
        """A streamed request and a one-shot request map to different keys."""
        one = json.dumps({"model": "m", "stream": False}).encode()
        streamed = json.dumps({"model": "m", "stream": True}).encode()
        assert RequestCanonicalizer.key("POST", CHAT_PATH, one) != \
            RequestCanonicalizer.key("POST", CHAT_PATH, streamed)

    def test_path_and_method_participate(self):
        """Method and path are part of the key, not just the body."""
        body = b"{}"
        assert RequestCanonicalizer.key("POST", "/chat/completions", body) != \
            RequestCanonicalizer.key("GET", "/chat/completions", body)


class TestCassette:
    """On-disk store: round-trip, atomic save, multi-response de-duplication."""

    def test_put_get_roundtrip(self, tmp_path):
        """A put entry is persisted and re-readable from a fresh Cassette."""
        path = str(tmp_path / "c.json")
        cassette = Cassette(path)
        cassette.put("k1", {"request": "r", "response": {"kind": "json", "status": 200}})
        assert os.path.exists(path)
        assert Cassette(path).get("k1")["response"]["status"] == 200

    def test_append_response_dedupes_ignoring_latency(self, tmp_path):
        """Identical response content (differing only in latency) is not duplicated."""
        path = str(tmp_path / "c.json")
        cassette = Cassette(path)
        meta = {"request": "r"}
        cassette.append_response("k", meta, {"kind": "json", "status": 200, "body": {"a": 1}, "latency_seconds": 0.1})
        cassette.append_response("k", meta, {"kind": "json", "status": 200, "body": {"a": 1}, "latency_seconds": 0.9})
        cassette.append_response("k", meta, {"kind": "json", "status": 200, "body": {"a": 2}, "latency_seconds": 0.2})
        assert len(cassette.get("k")["responses"]) == 2


class TestPlaybackDelay:
    """Per-response delay policy."""

    def test_none(self):
        """none mode never delays."""
        assert PlaybackDelay(PlaybackDelay.MODE_NONE).seconds_for({"latency_seconds": 1.0}) == 0.0

    def test_recorded_json_uses_latency(self):
        """recorded mode uses latency_seconds for a one-shot response."""
        assert PlaybackDelay(PlaybackDelay.MODE_RECORDED).seconds_for(
            {"kind": "json", "latency_seconds": 1.25}) == 1.25

    def test_recorded_stream_prefers_first_byte(self):
        """recorded mode uses first_byte_seconds for a streamed response."""
        response = {"kind": "stream", "latency_seconds": 5.0, "first_byte_seconds": 0.7}
        assert PlaybackDelay(PlaybackDelay.MODE_RECORDED).seconds_for(response) == 0.7

    def test_recorded_stream_falls_back_to_latency(self):
        """recorded mode falls back to latency_seconds when first_byte is absent."""
        response = {"kind": "stream", "latency_seconds": 5.0, "first_byte_seconds": None}
        assert PlaybackDelay(PlaybackDelay.MODE_RECORDED).seconds_for(response) == 5.0

    def test_recorded_missing_is_zero(self):
        """recorded mode with no recorded latency yields no delay."""
        assert PlaybackDelay(PlaybackDelay.MODE_RECORDED).seconds_for({"kind": "json"}) == 0.0

    def test_fixed(self):
        """fixed mode returns the configured constant."""
        assert PlaybackDelay(PlaybackDelay.MODE_FIXED, fixed_seconds=0.4).seconds_for({}) == 0.4

    def test_random_within_range(self):
        """random mode returns values within the configured range."""
        delay = PlaybackDelay(PlaybackDelay.MODE_RANDOM, min_seconds=0.2, max_seconds=0.5)
        assert all(0.2 <= delay.seconds_for({}) <= 0.5 for _ in range(50))


class TestCassetteCleaner:
    """Removing recorded failures while preserving valid entries and unknown fields."""

    def test_clean_entries_mixed(self):
        """Failures are dropped/trimmed; successes and unknown fields survive; stats are correct."""
        entries = [
            {"key": "k1", "response": {"kind": "json", "status": 200}},                       # keep
            {"key": "k2", "response": {"kind": "json", "status": 429}},                        # drop (failure)
            {"key": "k3", "responses": [                                                       # trim to 2xx
                {"kind": "json", "status": 200, "body": {"a": 1}},
                {"kind": "json", "status": 500, "body": {}},
                {"kind": "json", "status": 200, "body": {"a": 2}},
            ]},
            {"key": "k4", "responses": [{"kind": "json", "status": 503}]},                     # drop (all failure)
            {"key": "k5"},                                                                     # drop (malformed)
        ]
        cleaned, stats = CassetteCleaner.clean_entries(entries)
        assert [entry["key"] for entry in cleaned] == ["k1", "k3"]
        assert [r["body"]["a"] for r in cleaned[1]["responses"]] == [1, 2]
        assert stats["kept"] == 2
        assert stats["dropped_failure"] == 2
        assert stats["dropped_malformed"] == 1
        assert stats["variants_removed"] == 1

    def test_clean_is_idempotent(self):
        """Cleaning an already-clean cassette removes nothing."""
        entries = [{"key": "k1", "response": {"kind": "json", "status": 200}}]
        once, _ = CassetteCleaner.clean_entries(entries)
        twice, stats = CassetteCleaner.clean_entries(once)
        assert len(twice) == 1 and stats["dropped_failure"] == 0 and stats["variants_removed"] == 0


class TestProxyIntegration:
    """In-process record/playback/hybrid behavior against a fake upstream."""

    @pytest.mark.asyncio
    async def test_record_then_playback_json(self, start_app, tmp_path):
        """Record a one-shot response, then replay it byte-identical without hitting upstream."""
        box = {"n": 0}
        upstream = start_app(tornado.web.Application([(CHAT_PATH, _CountingUpstream, {"box": box})]))
        path = str(tmp_path / "c.json")

        rec = ProxyState(mode=ProxyState.MODE_RECORD, cassette=Cassette(path), upstream=_upstream_client(upstream))
        rec_url = start_app(RecordPlaybackLlmServer.build_app(rec))
        code, body = await _post(rec_url + CHAT_PATH, PAYLOAD)
        assert code == 200 and _content(body) == "resp-1"
        assert box["n"] == 1

        pb = ProxyState(mode=ProxyState.MODE_PLAYBACK, cassette=Cassette(path))
        pb_url = start_app(RecordPlaybackLlmServer.build_app(pb))
        code2, body2 = await _post(pb_url + CHAT_PATH, PAYLOAD)
        assert code2 == 200 and json.loads(body2) == json.loads(body)   # byte-identical replay
        assert box["n"] == 1                                            # upstream NOT hit on playback

    @pytest.mark.asyncio
    async def test_record_then_playback_stream(self, start_app, tmp_path):
        """Record a streamed SSE response, then replay it without hitting upstream."""
        box = {"n": 0}
        upstream = start_app(tornado.web.Application([(CHAT_PATH, _StreamUpstream, {"box": box})]))
        path = str(tmp_path / "c.json")

        rec = ProxyState(mode=ProxyState.MODE_RECORD, cassette=Cassette(path), upstream=_upstream_client(upstream))
        rec_url = start_app(RecordPlaybackLlmServer.build_app(rec))
        code, body = await _post(rec_url + CHAT_PATH, PAYLOAD, stream=True)
        assert code == 200 and b"from" in body and b"[DONE]" in body

        pb = ProxyState(mode=ProxyState.MODE_PLAYBACK, cassette=Cassette(path))
        pb_url = start_app(RecordPlaybackLlmServer.build_app(pb))
        code2, body2 = await _post(pb_url + CHAT_PATH, PAYLOAD, stream=True)
        assert code2 == 200 and b"Hello" in body2 and b"upstream" in body2 and b"[DONE]" in body2
        assert box["n"] == 1                                            # upstream NOT hit on playback

    @pytest.mark.asyncio
    async def test_playback_miss_returns_504(self, start_app, tmp_path):
        """A request with no recorded match fails hard with HTTP 504 in playback mode."""
        pb = ProxyState(mode=ProxyState.MODE_PLAYBACK, cassette=Cassette(str(tmp_path / "empty.json")))
        pb_url = start_app(RecordPlaybackLlmServer.build_app(pb))
        code, body = await _post(pb_url + CHAT_PATH, PAYLOAD)
        assert code == 504 and b"no recorded response" in body

    @pytest.mark.asyncio
    async def test_multi_response_roundrobin(self, start_app, tmp_path):
        """Multi-response records distinct variants and plays them back round-robin."""
        box = {"n": 0}
        upstream = start_app(tornado.web.Application([(CHAT_PATH, _CountingUpstream, {"box": box})]))
        path = str(tmp_path / "c.json")

        rec = ProxyState(mode=ProxyState.MODE_RECORD, cassette=Cassette(path),
                         upstream=_upstream_client(upstream), multi_response=True)
        rec_url = start_app(RecordPlaybackLlmServer.build_app(rec))
        for _ in range(3):
            await _post(rec_url + CHAT_PATH, PAYLOAD)
        assert len(list(Cassette(path).entries.values())[0]["responses"]) == 3

        pb = ProxyState(mode=ProxyState.MODE_PLAYBACK, cassette=Cassette(path), multi_response=True)
        pb_url = start_app(RecordPlaybackLlmServer.build_app(pb))
        seen = [_content((await _post(pb_url + CHAT_PATH, PAYLOAD))[1]) for _ in range(4)]
        assert seen == ["resp-1", "resp-2", "resp-3", "resp-1"]         # round-robin with wrap

    @pytest.mark.asyncio
    async def test_hybrid_records_on_miss_then_hits(self, start_app, tmp_path):
        """Hybrid fetches+records on a miss, then serves the recorded response on a hit."""
        box = {"n": 0}
        upstream = start_app(tornado.web.Application([(CHAT_PATH, _CountingUpstream, {"box": box})]))
        path = str(tmp_path / "c.json")

        state = ProxyState(mode=ProxyState.MODE_HYBRID, cassette=Cassette(path), upstream=_upstream_client(upstream))
        url = start_app(RecordPlaybackLlmServer.build_app(state))

        _, first = await _post(url + CHAT_PATH, PAYLOAD)                # miss -> fetch + record
        assert box["n"] == 1
        _, second = await _post(url + CHAT_PATH, PAYLOAD)              # hit -> from cassette
        assert box["n"] == 1                                           # upstream NOT hit again
        assert _content(first) == _content(second)
        assert len(Cassette(path)) == 1

    @pytest.mark.asyncio
    async def test_hybrid_miss_without_upstream_returns_504(self, start_app, tmp_path):
        """Hybrid with no upstream behaves like plain playback: a miss is a 504."""
        state = ProxyState(mode=ProxyState.MODE_HYBRID, cassette=Cassette(str(tmp_path / "empty.json")), upstream=None)
        url = start_app(RecordPlaybackLlmServer.build_app(state))
        code, _ = await _post(url + CHAT_PATH, PAYLOAD)
        assert code == 504

    @pytest.mark.asyncio
    async def test_non_2xx_relayed_but_not_recorded(self, start_app, tmp_path):
        """A non-2xx upstream response is relayed to the caller but never cached."""
        upstream = start_app(tornado.web.Application([(CHAT_PATH, _RateLimitedUpstream)]))
        path = str(tmp_path / "c.json")
        state = ProxyState(mode=ProxyState.MODE_RECORD, cassette=Cassette(path), upstream=_upstream_client(upstream))
        url = start_app(RecordPlaybackLlmServer.build_app(state))

        code, body = await _post(url + CHAT_PATH, PAYLOAD)
        assert code == 429 and b"Too Many Requests" in body           # relayed to caller
        assert len(Cassette(path)) == 0                               # not recorded
        assert not os.path.exists(path)                              # nothing written at all
