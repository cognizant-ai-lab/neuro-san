
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
See class comment for details.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import time

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import tornado.httpclient
import tornado.iostream
import tornado.web
import tornado.ioloop

from tests.record_playback_llm_server.proxy_state import ProxyState
from tests.record_playback_llm_server.request_canonicalizer import RequestCanonicalizer


class ProxyHandler(tornado.web.RequestHandler):
    """
    Shared record/playback/hybrid logic for the proxy endpoints.

    In RECORD mode the handler forwards the request to the real external LLM
    host, tees the response into the cassette (capturing wall-clock latency),
    and relays it back to the caller (both one-shot JSON and streamed SSE). In
    PLAYBACK mode it looks the request up in the cassette by its canonical
    signature and replays the recorded response, never touching the network. In
    HYBRID mode it behaves like playback, except a miss falls through to the
    real host (when one is configured), records the result into the current
    cassette, and returns it -- a self-healing cassette.

    With multi-response enabled, RECORD (and hybrid-mode record-on-miss)
    accumulate every distinct response for a request and PLAYBACK serves them
    round-robin; otherwise a request maps to a single response.

    On a genuine playback miss (playback mode, or hybrid mode with no
    upstream) the handler fails hard with HTTP 504 so a load/regression test
    surfaces the gap deterministically rather than silently faking data.
    """

    SSE_FRAME_DELIMITER: str = "\n\n"

    def initialize(self, state: ProxyState, upstream_path: str) -> None:
        """
        Receive shared state and the upstream sub-path for this route.
        :param state: The process-wide ProxyState.
        :param upstream_path: The path to forward to on the external host,
                              e.g. "/chat/completions".
        """
        # pylint: disable=attribute-defined-outside-init
        self.state: ProxyState = state
        self.upstream_path: str = upstream_path
        self.logger: logging.Logger = logging.getLogger("record-playback-llm")

    def data_received(self, chunk):
        """Required override of RequestHandler abstract method; full body comes via self.request.body."""
        return

    async def handle_request(self, method: str, body_bytes: bytes) -> None:
        """
        Entry point used by the concrete endpoint handlers.
        :param method: HTTP method of the incoming request.
        :param body_bytes: Raw request body bytes (may be empty).
        """
        key: str = RequestCanonicalizer.key(method, self.upstream_path, body_bytes)
        if self.state.is_record():
            await self._record(method, body_bytes, key)
        else:
            # playback and hybrid both serve from the cassette; they differ
            # only in what happens on a miss (see _playback).
            await self._playback(method, body_bytes, key)

    def _wants_stream(self, body_bytes: bytes) -> bool:
        """:return: True if the request body asks for a streamed (SSE) response."""
        body: Dict[str, Any] = RequestCanonicalizer.parsed_body(body_bytes)
        return bool(body.get("stream", False))

    async def _record(self, method: str, body_bytes: bytes, key: str) -> None:
        """Forward to the external host, relay the response, and store it."""
        if self.state.upstream is None:
            self.set_status(500)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"error": {"message": "record mode has no upstream configured"}}))
            return

        if self._wants_stream(body_bytes):
            await self._record_stream(method, body_bytes, key)
        else:
            await self._record_json(method, body_bytes, key)

    async def _record_json(self, method: str, body_bytes: bytes, key: str) -> None:
        """Record and relay a one-shot JSON response, capturing upstream latency."""
        started: float = time.monotonic()
        try:
            response: tornado.httpclient.HTTPResponse = \
                await self.state.upstream.fetch(self.upstream_path, method, body_bytes)
        except (OSError, tornado.httpclient.HTTPError) as exception:
            self._fail_upstream(exception)
            return
        latency_seconds: float = time.monotonic() - started

        raw_body: bytes = response.body or b""
        self.set_status(response.code)
        self.set_header("Content-Type", "application/json")
        self.write(bytes(raw_body))

        if self._store(method, body_bytes, key, {
            "kind": "json",
            "status": response.code,
            "body": self._decode_body(raw_body),
            "latency_seconds": round(latency_seconds, 6),
        }):
            self.logger.info("recorded json response (%d bytes, %.3fs) key=%s",
                             len(raw_body), latency_seconds, key[:12])

    async def _record_stream(self, method: str, body_bytes: bytes, key: str) -> None:
        """
        Record and relay a streamed response, teeing chunks to disk with latency.

        The upstream status is not known until its headers arrive, which (via
        header_callback) precedes the first body chunk. The client's status and
        headers are therefore set on the first chunk rather than up front: a 2xx
        is streamed as SSE; a non-2xx (401/429/5xx, whose body is typically JSON,
        not SSE) is relayed with the real status and content-type. Only
        successful responses are recorded (see _store).
        """
        accumulated = bytearray()
        started: float = time.monotonic()
        # Mutable state shared with the synchronous header/chunk callbacks.
        stream_state: Dict[str, Any] = {
            "status": None, "content_type": None,
            "headers_started": False, "first_byte_seconds": None,
        }

        def on_header(line: str) -> None:
            stripped: str = line.strip()
            if not stripped:
                return
            if stripped.startswith("HTTP/"):
                # Status line, e.g. "HTTP/1.1 429 Too Many Requests". Reset the
                # content-type so a redirect/retry block cannot leak a stale one.
                parts = stripped.split(None, 2)
                if len(parts) >= 2 and parts[1].isdigit():
                    stream_state["status"] = int(parts[1])
                stream_state["content_type"] = None
                return
            name, separator, value = stripped.partition(":")
            if separator and name.strip().lower() == "content-type":
                stream_state["content_type"] = value.strip()

        def on_chunk(chunk: bytes) -> None:
            if stream_state["first_byte_seconds"] is None:
                stream_state["first_byte_seconds"] = time.monotonic() - started
            accumulated.extend(chunk)
            try:
                if not stream_state["headers_started"]:
                    self._begin_stream_relay(stream_state["status"], stream_state["content_type"])
                    stream_state["headers_started"] = True
                self.write(bytes(chunk))
                # Flush on the event loop so the caller sees tokens progressively.
                tornado.ioloop.IOLoop.current().spawn_callback(self._safe_flush)
            except tornado.iostream.StreamClosedError:
                # Client disconnected mid-stream; nothing more to do.
                pass

        try:
            response: tornado.httpclient.HTTPResponse = await self.state.upstream.fetch_stream(
                self.upstream_path, method, body_bytes, on_chunk, on_header)
        except (OSError, tornado.httpclient.HTTPError) as exception:
            self._fail_upstream(exception)
            return
        latency_seconds: float = time.monotonic() - started

        # Empty body (e.g. an error with no body): no chunk arrived, so set the
        # status now that the response object is known.
        if not stream_state["headers_started"]:
            self._begin_stream_relay(response.code, response.headers.get("Content-Type"))

        await self._safe_flush()
        first_byte: Optional[float] = stream_state["first_byte_seconds"]
        frames: List[str] = self._split_sse_frames(bytes(accumulated))
        if self._store(method, body_bytes, key, {
            "kind": "stream",
            "status": response.code,
            "chunks": frames,
            "latency_seconds": round(latency_seconds, 6),
            "first_byte_seconds": round(first_byte, 6) if first_byte is not None else None,
        }):
            self.logger.info("recorded stream response (%d frames, %.3fs) key=%s",
                             len(frames), latency_seconds, key[:12])

    def _begin_stream_relay(self, status: Optional[int], content_type: Optional[str]) -> None:
        """
        Set the client response status/headers for a streamed relay once the
        upstream status is known. A 2xx is streamed as Server-Sent Events; any
        other status is relayed with the upstream's real status and content-type
        (LLM error bodies are JSON, not SSE).
        """
        code: int = status if status is not None else 200
        self.set_status(code)
        if 200 <= code < 300:
            self.set_header("Content-Type", "text/event-stream")
            self.set_header("Cache-Control", "no-cache")
            self.set_header("X-Accel-Buffering", "no")
        else:
            self.set_header("Content-Type", content_type or "application/json")

    def _store(self, method: str, body_bytes: bytes, key: str, response: Dict[str, Any]) -> bool:
        """
        Persist a recorded response, but only when it is a success (HTTP 2xx).
        Non-2xx responses (rate limits, auth errors, upstream 5xx, ...) are
        relayed to the caller but never cached, so a transient failure cannot
        poison the cassette; a later retry can record a good response instead.

        In single-response mode the entry keeps one "response"; in multi-response
        mode distinct responses accumulate under a "responses" list.
        :return: True if the response was persisted, False if skipped as non-2xx.
        """
        status: int = response.get("status", 0)
        if not self._is_success(status):
            self.logger.warning("not recording non-2xx response (status=%s) key=%s", status, key[:12])
            return False
        meta: Dict[str, Any] = {
            "method": method.upper(),
            "path": self.upstream_path,
            "request": RequestCanonicalizer.canonical_string(method, self.upstream_path, body_bytes),
        }
        if self.state.multi_response:
            self.state.cassette.append_response(key, meta, response)
        else:
            entry: Dict[str, Any] = dict(meta)
            entry["response"] = response
            self.state.cassette.put(key, entry)
        return True

    @staticmethod
    def _is_success(status: int) -> bool:
        """:return: True if the HTTP status is a 2xx success."""
        return 200 <= status < 300

    async def _playback(self, method: str, body_bytes: bytes, key: str) -> None:
        """
        Serve a recorded response. On a miss: in hybrid mode with an upstream
        configured, fall through to the real host and record the result into the
        current cassette (self-healing); otherwise fail hard with 504.
        """
        entry: Dict[str, Any] = self.state.cassette.get(key)
        if entry is None:
            if self.state.is_hybrid() and self.state.upstream is not None:
                self.logger.info("hybrid miss key=%s -> forwarding to upstream and recording", key[:12])
                await self._record(method, body_bytes, key)
                return
            self.logger.warning("playback miss for key=%s (%s %s)", key[:12], self.request.method, self.upstream_path)
            self._dump_miss_diff(key)
            self.set_status(504)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"error": {
                "message": "no recorded response for this request in playback mode",
                "key": key,
            }}))
            return

        response: Dict[str, Any] = self._select_response(entry, key)

        # Up-front latency emulation before serving the hit. Each response
        # carries its own recorded latency, so in multi-response round-robin the
        # per-response recorded delay is honored.
        delay_seconds: float = self.state.playback_delay.seconds_for(response)
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        if response.get("kind") == "stream":
            await self._replay_stream(response)
        else:
            self._replay_json(response)

    def _select_response(self, entry: Dict[str, Any], key: str) -> Dict[str, Any]:
        """
        Pick the response to replay. Multi-response entries carry a "responses"
        list served round-robin; single-response entries carry one "response".
        """
        responses: Any = entry.get("responses")
        if isinstance(responses, list) and responses:
            index: int = self.state.next_rotation_index(key, len(responses))
            return responses[index]
        return entry.get("response", {})

    async def _replay_stream(self, response: Dict[str, Any]) -> None:
        """Re-emit recorded SSE frames, optionally pacing between them."""
        self.set_status(response.get("status", 200))
        self.set_header("Content-Type", "text/event-stream")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("X-Accel-Buffering", "no")
        try:
            for frame in response.get("chunks", []):
                self.write(frame)
                await self.flush()
                if self.state.stream_replay_delay > 0:
                    await asyncio.sleep(self.state.stream_replay_delay)
        except tornado.iostream.StreamClosedError:
            # Client disconnected mid-stream; nothing more to do.
            return

    def _replay_json(self, response: Dict[str, Any]) -> None:
        """Write back a recorded one-shot JSON response."""
        self.set_status(response.get("status", 200))
        self.set_header("Content-Type", "application/json")
        body: Any = response.get("body")
        if isinstance(body, (dict, list)):
            self.write(json.dumps(body))
        elif body is not None:
            self.write(str(body))

    def _dump_miss_diff(self, key: str) -> None:
        """
        Debug aid for playback misses. When RECORD_PLAYBACK_DEBUG_MISS is set,
        write a readable diff between the (missed) incoming request and its
        closest recorded neighbor to "<cassette>.miss-<key8>.diff", so the
        exact non-deterministic field can be pinpointed. Best-effort: never
        let diagnostics disturb request handling.
        """
        if not os.environ.get("RECORD_PLAYBACK_DEBUG_MISS"):
            return
        try:
            incoming: str = RequestCanonicalizer.canonical_string(
                self.request.method, self.upstream_path, self.request.body or b"")
            best, ratio = self._closest_recorded(incoming)
            diff_text: str = "\n".join(difflib.unified_diff(
                self._pretty(best).splitlines(),
                self._pretty(incoming).splitlines(),
                fromfile="closest_recorded_request",
                tofile="incoming_playback_request",
                lineterm=""))
            out_path: str = f"{self.state.cassette.path}.miss-{key[:8]}.diff"
            with open(out_path, "w", encoding="utf-8") as diff_file:
                diff_file.write(f"# closest recorded request match ratio: {ratio:.3f}\n")
                diff_file.write(diff_text)
            self.logger.warning("wrote playback-miss diff to %s (closest match ratio %.3f)", out_path, ratio)
        except Exception as exception:  # pylint: disable=broad-exception-caught
            self.logger.error("failed to write playback-miss diff: %s", str(exception))

    def _closest_recorded(self, incoming: str) -> Tuple[str, float]:
        """Find the recorded request most similar to the incoming one."""
        matcher = difflib.SequenceMatcher()
        matcher.set_seq2(incoming)
        best: str = ""
        best_ratio: float = 0.0
        for entry in self.state.cassette.entries.values():
            candidate: str = entry.get("request", "")
            matcher.set_seq1(candidate)
            ratio: float = matcher.quick_ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = candidate
        return best, best_ratio

    @staticmethod
    def _pretty(canonical: str) -> str:
        """Pretty-print the JSON body of a canonical request for readable diffing."""
        header: str = canonical
        body_text: str = ""
        newline_index: int = canonical.find("\n")
        if newline_index >= 0:
            header = canonical[:newline_index]
            body_text = canonical[newline_index + 1:]
        parsed: Optional[Any] = None
        try:
            parsed = json.loads(body_text)
        except (json.JSONDecodeError, ValueError):
            return canonical
        return header + "\n" + json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False)

    async def _safe_flush(self) -> None:
        """Flush the response buffer, tolerating a client that has disconnected."""
        try:
            await self.flush()
        except tornado.iostream.StreamClosedError:
            return

    def _fail_upstream(self, exception: Exception) -> None:
        """Report an upstream forwarding failure as a 502 without recording it."""
        self.logger.error("upstream request to %s failed: %s", self.upstream_path, str(exception))
        self.set_status(502)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"error": {"message": "upstream request failed"}}))

    @staticmethod
    def _decode_body(raw_body: bytes) -> Any:
        """Parse a response body as JSON for diff-friendly storage; fall back to text."""
        if not raw_body:
            return ""
        try:
            return json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            return raw_body.decode("utf-8", errors="replace")

    @staticmethod
    def _split_sse_frame_bytes(raw: bytes) -> List[bytes]:
        """
        Split an accumulated SSE byte stream into event frames while preserving
        the exact original delimiter bytes. Supports both LF and CRLF blank-line
        delimiters and leaves any trailing unterminated bytes unchanged.
        """
        frames: List[bytes] = []
        start: int = 0
        raw_length: int = len(raw)

        while start < raw_length:
            lf_index: int = raw.find(b"\n\n", start)
            crlf_index: int = raw.find(b"\r\n\r\n", start)

            delimiter_index: int = -1
            delimiter: bytes = b""
            if lf_index == -1:
                delimiter_index = crlf_index
                delimiter = b"\r\n\r\n" if crlf_index != -1 else b""
            elif crlf_index == -1 or lf_index < crlf_index:
                delimiter_index = lf_index
                delimiter = b"\n\n"
            else:
                delimiter_index = crlf_index
                delimiter = b"\r\n\r\n"

            if delimiter_index == -1:
                if start < raw_length:
                    frames.append(raw[start:])
                break

            frame_end: int = delimiter_index + len(delimiter)
            if frame_end > start:
                frames.append(raw[start:frame_end])
            start = frame_end

        return frames

    @classmethod
    def _split_sse_frames(cls, raw: bytes) -> List[str]:
        """
        Split an accumulated SSE byte stream into individual event frames.
        The recorded byte chunks are TCP-sized, not frame-aligned, so we
        re-split on the SSE blank-line delimiter while preserving the exact
        delimiter bytes found upstream. This yields semantic event units for
        clean replay without changing the recorded byte stream.
        """
        return [
            frame.decode("utf-8", errors="replace")
            for frame in cls._split_sse_frame_bytes(raw)
            if frame != b""
        ]
