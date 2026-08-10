
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

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import tornado.httpclient
import tornado.iostream
import tornado.web

from tests.record_playback_llm_server.proxy_state import ProxyState
from tests.record_playback_llm_server.request_canonicalizer import RequestCanonicalizer


class ProxyHandler(tornado.web.RequestHandler):
    """
    Shared record/playback logic for the proxy endpoints.

    In RECORD mode the handler forwards the request to the real external LLM
    host, tees the response into the cassette, and relays it back to the
    caller (both one-shot JSON and streamed SSE). In PLAYBACK mode it looks
    the request up in the cassette by its canonical signature and replays the
    recorded response, never touching the network.

    On a playback miss the handler fails hard with HTTP 504 so a
    load/regression test surfaces the gap deterministically rather than
    silently substituting fabricated data.
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
        if self.state.is_playback():
            await self._playback(key)
        else:
            await self._record(method, body_bytes, key)

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
        """Record and relay a one-shot JSON response."""
        try:
            response: tornado.httpclient.HTTPResponse = \
                await self.state.upstream.fetch(self.upstream_path, method, body_bytes)
        except (OSError, tornado.httpclient.HTTPError) as exception:
            self._fail_upstream(exception)
            return

        raw_body: bytes = response.body or b""
        self.set_status(response.code)
        self.set_header("Content-Type", "application/json")
        self.write(bytes(raw_body))

        self.state.cassette.put(key, {
            "method": method.upper(),
            "path": self.upstream_path,
            "request": RequestCanonicalizer.canonical_string(method, self.upstream_path, body_bytes),
            "response": {
                "kind": "json",
                "status": response.code,
                "body": self._decode_body(raw_body),
            },
        })
        self.logger.info("recorded json response (%d bytes) key=%s", len(raw_body), key[:12])

    async def _record_stream(self, method: str, body_bytes: bytes, key: str) -> None:
        """Record and relay a streamed SSE response, teeing chunks to disk."""
        self.set_header("Content-Type", "text/event-stream")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("X-Accel-Buffering", "no")

        accumulated = bytearray()

        def on_chunk(chunk: bytes) -> None:
            accumulated.extend(chunk)
            self.write(bytes(chunk))
            # Flush must happen on the event loop; schedule it as a coroutine so
            # the caller (neuro-san) sees tokens progressively during recording.
            tornado.ioloop.IOLoop.current().spawn_callback(self._safe_flush)

        try:
            response: tornado.httpclient.HTTPResponse = await self.state.upstream.fetch_stream(
                self.upstream_path, method, body_bytes, on_chunk)
        except (OSError, tornado.httpclient.HTTPError) as exception:
            self._fail_upstream(exception)
            return

        await self._safe_flush()
        frames: List[str] = self._split_sse_frames(bytes(accumulated))
        self.state.cassette.put(key, {
            "method": method.upper(),
            "path": self.upstream_path,
            "request": RequestCanonicalizer.canonical_string(method, self.upstream_path, body_bytes),
            "response": {
                "kind": "stream",
                "status": response.code,
                "chunks": frames,
            },
        })
        self.logger.info("recorded stream response (%d frames) key=%s", len(frames), key[:12])

    async def _playback(self, key: str) -> None:
        """Replay a recorded response, or fail hard on a miss."""
        entry: Dict[str, Any] = self.state.cassette.get(key)
        if entry is None:
            self.logger.warning("playback miss for key=%s (%s %s)", key[:12], self.request.method, self.upstream_path)
            self._dump_miss_diff(key)
            self.set_status(504)
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"error": {
                "message": "no recorded response for this request in playback mode",
                "key": key,
            }}))
            return

        response: Dict[str, Any] = entry.get("response", {})
        if response.get("kind") == "stream":
            await self._replay_stream(response)
        else:
            self._replay_json(response)

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
        self.write(json.dumps({"error": {"message": f"upstream request failed: {exception}"}}))

    @staticmethod
    def _decode_body(raw_body: bytes) -> Any:
        """Parse a response body as JSON for diff-friendly storage; fall back to text."""
        if not raw_body:
            return ""
        try:
            return json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            return raw_body.decode("utf-8", errors="replace")

    @classmethod
    def _split_sse_frames(cls, raw: bytes) -> List[str]:
        """
        Split an accumulated SSE byte stream into individual event frames.
        The recorded byte chunks are TCP-sized, not frame-aligned, so we
        re-split on the SSE blank-line delimiter and re-append it to each
        frame. This yields semantic event units for clean replay.
        """
        text: str = raw.decode("utf-8", errors="replace")
        frames: List[str] = []
        for part in text.split(cls.SSE_FRAME_DELIMITER):
            if part == "":
                continue
            frames.append(f"{part}{cls.SSE_FRAME_DELIMITER}")
        return frames
