
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
from typing import Any
from typing import AsyncIterator
from typing import Callable
from typing import Dict
from typing import Optional

import contextvars
import datetime
import json
import logging
import time
import uuid


class HttpxLlmTracer:
    """
    HTTP-layer tracer for outbound LLM traffic that flows through
    httpx.AsyncClient. Emits structured JSON log events so post-run
    analysis (grep, jq, pandas) can reconstruct per-request lifecycles.

    Events emitted (one line each, via the dedicated logger
    "neuro_san.diagnostics.http_llm_trace"):

      - http_llm_out  : request sent. Fields include attempt_id,
                        provider (host-inferred), method, url, req_bytes,
                        user_req_id (from ContextVar).
      - http_llm_in   : response HEADERS received. Fields include the
                        same attempt_id, HTTP status, elapsed_ms since
                        out, and server_req_id (from openai-request-id
                        / x-request-id headers where present). For
                        streaming responses this is TTFT, not stream end.
      - http_llm_end  : response body FULLY consumed OR the response was
                        closed. Fields include attempt_id, elapsed_ms
                        (total), reason (stream_complete / aclose /
                        stream_error:<ExcType> / stream_generator_exit),
                        stream_bytes (total bytes read).
      - http_llm_chunk: (optional, per-chunk) one line per received body
                        chunk. Only emitted when
                        AGENT_HTTP_LLM_TRACE_CHUNKS is enabled -- log
                        volume is huge (dozens per LLM call).
      - http_llm_err  : (implicit) if the response never arrives, only
                        http_llm_out is emitted; readers detect missing
                        http_llm_in / http_llm_end as errors. Explicit
                        transport failures inside body iteration are
                        surfaced via http_llm_end with reason
                        "stream_error:...".

    Every event carries "user_req_id" read from a ContextVar. Set the
    ContextVar at the boundary of each user-facing request (e.g. in the
    Tornado handler entry point) via set_user_request_id(); asyncio and
    executor bridges propagate context automatically, so every LLM call
    triggered downstream will inherit the same id.

    Correlation:
      grep 'user_req_id=<id>' http_llm_trace.log  gives the whole LLM
      lifecycle of one user request in time order, with attempt_ids
      grouping any retries.

    Installation is one-shot: call install(...) once at server startup,
    before any LLM client is constructed. install() monkey-patches
    httpx.AsyncClient.__init__ to inject event_hooks on every future
    client, regardless of which provider SDK creates it. Idempotent --
    a second call is a no-op.
    """

    # Class-level singleton state. ContextVar behavior is per-context, not
    # per-instance, so keeping this on the class is correct.
    _user_req_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
        "neuro_san_http_llm_trace_user_req_id", default=None
    )
    _installed: bool = False
    _include_bodies: bool = False
    _include_chunks: bool = False
    _logger: Optional[logging.Logger] = None
    # Sentinel-free "did we already emit end?" flag stored per response
    # via response.extensions["_llm_trace_end_emitted"]. Prevents double
    # emit when both aiter_* and aclose fire.

    @classmethod
    def install(cls,
                include_bodies: bool = False,
                include_chunks: bool = False) -> None:
        """
        Monkey-patch httpx.AsyncClient.__init__ so every future client
        instance gets our event hooks. Must be called BEFORE any provider
        SDK constructs its client (i.e. at server startup, before the
        first LLM call).

        :param include_bodies: When True, request and response bodies are
                    logged verbatim on http_llm_out and http_llm_end.
                    Prompts + completions are large and sensitive; off
                    by default.
        :param include_chunks: When True, one http_llm_chunk event is
                    emitted per received body chunk. Massive log volume;
                    off by default. Enable only when investigating
                    inter-chunk cadence specifically.
        """
        if cls._installed:
            return
        cls._include_bodies = include_bodies
        cls._include_chunks = include_chunks
        cls._logger = logging.getLogger("neuro_san.diagnostics.http_llm_trace")

        # Import here so the module can be imported without httpx present
        # (httpx is a transitive dependency, always installed in neuro-san
        # but keeping the import local reduces coupling for tests).
        # pylint: disable=import-outside-toplevel
        import httpx

        original_init: Callable = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            existing_hooks: Dict[str, list] = kwargs.pop("event_hooks", None) or {}
            merged_hooks: Dict[str, list] = {
                "request": [cls._on_request] + list(existing_hooks.get("request", [])),
                "response": [cls._on_response] + list(existing_hooks.get("response", [])),
            }
            kwargs["event_hooks"] = merged_hooks
            original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = patched_init
        cls._installed = True
        cls._logger.info(
            "HttpxLlmTracer installed (include_bodies=%s include_chunks=%s)",
            include_bodies, include_chunks)

    @classmethod
    def set_user_request_id(cls, user_req_id: str) -> None:
        """
        Set the current user-request id on the ContextVar. Call this
        at the entry point of each user-facing request (e.g. the top of
        Tornado's post() method). asyncio and executor bridges propagate
        the ContextVar automatically, so every httpx call made downstream
        will pick up the same id.

        :param user_req_id: Short identifier (typically a UUID prefix)
                    used to correlate every LLM event in one user
                    request. Include in log routing / grep as
                    "user_req_id=<id>".
        """
        cls._user_req_id_var.set(user_req_id)

    @classmethod
    def get_user_request_id(cls) -> Optional[str]:
        """
        Return the current user-request id from the ContextVar, or None
        if not set in the current context.
        """
        return cls._user_req_id_var.get()

    # -------------------------------------------------------------------
    # httpx event hooks
    # -------------------------------------------------------------------

    @classmethod
    async def _on_request(cls, request) -> None:
        """
        httpx request hook: record the outbound request, attach a
        unique attempt_id + start timestamp to the request extensions
        so the paired response/end events can compute elapsed time.
        """
        attempt_id: str = uuid.uuid4().hex[:8]
        start_ns: int = time.monotonic_ns()
        request.extensions["_llm_trace_attempt_id"] = attempt_id
        request.extensions["_llm_trace_start_ns"] = start_ns

        fields: Dict[str, Any] = {
            "attempt_id": attempt_id,
            "provider": cls._infer_provider(request.url.host),
            "host": request.url.host,
            "method": request.method,
            "url": str(request.url.copy_with(query=None)),
            "req_bytes": len(request.content) if request.content else 0,
        }
        if cls._include_bodies and request.content:
            fields["req_body"] = cls._safe_decode(request.content)
        cls._emit("http_llm_out", **fields)

    @classmethod
    async def _on_response(cls, response) -> None:
        """
        httpx response hook: record that headers arrived, then wrap the
        response body iterator + aclose so we can emit http_llm_end when
        the body is fully consumed or the response is closed.
        """
        request = response.request
        attempt_id: str = request.extensions.get("_llm_trace_attempt_id", "unknown")
        start_ns: int = request.extensions.get("_llm_trace_start_ns", time.monotonic_ns())
        elapsed_ms: float = (time.monotonic_ns() - start_ns) / 1e6

        server_req_id: Optional[str] = (
            response.headers.get("openai-request-id")
            or response.headers.get("x-request-id")
            or response.headers.get("x-amzn-requestid")
        )
        cls._emit(
            "http_llm_in",
            attempt_id=attempt_id,
            status=response.status_code,
            elapsed_ms=round(elapsed_ms, 3),
            server_req_id=server_req_id,
        )
        cls._wrap_response_for_end(response, attempt_id, start_ns)

    @classmethod
    def _wrap_response_for_end(cls, response, attempt_id: str, start_ns: int) -> None:
        """
        Replace the response's aiter_raw and aclose with wrappers that
        emit http_llm_end exactly once when the body is fully consumed
        or the response is closed. aiter_bytes / aiter_text / aiter_lines
        all funnel through aiter_raw in httpx, so wrapping aiter_raw is
        sufficient to catch all body-iteration paths (including the
        internal .aread() path used by non-streaming responses).

        Firing rules (avoids httpx's aclose-during-iteration race):
          - The wrapped iterator's own paths (complete / GeneratorExit /
            other exception) always emit end. These are the authoritative
            events for the response's lifecycle.
          - aclose emits end only if the wrapped iterator was never
            entered (i.e. response was closed without reading the body).
            If iteration started, aclose trusts the iterator to emit end
            via one of its own paths -- necessary because httpx invokes
            aclose synchronously from inside the underlying stream's
            exhaustion handling, BEFORE the wrapped iterator's post-loop
            code has run.
        """
        # State kept on response.extensions so it travels with the
        # response object and is trivially inspectable in debugger.
        response.extensions["_llm_trace_end_emitted"] = False
        response.extensions["_llm_trace_iter_started"] = False

        def emit_end(reason: str, bytes_read: int) -> None:
            if response.extensions.get("_llm_trace_end_emitted"):
                return
            response.extensions["_llm_trace_end_emitted"] = True
            elapsed_ms: float = (time.monotonic_ns() - start_ns) / 1e6
            fields: Dict[str, Any] = {
                "attempt_id": attempt_id,
                "elapsed_ms": round(elapsed_ms, 3),
                "reason": reason,
                "stream_bytes": bytes_read,
            }
            if cls._include_bodies:
                # Response body is captured chunk-by-chunk in the wrapper
                # and stashed on extensions so we can attach it here.
                captured: Optional[bytes] = response.extensions.get("_llm_trace_body_buf")
                if captured is not None:
                    fields["resp_body"] = cls._safe_decode(captured)
            cls._emit("http_llm_end", **fields)

        original_aiter_raw: Callable = response.aiter_raw
        original_aclose: Callable = response.aclose
        include_chunks: bool = cls._include_chunks
        include_bodies: bool = cls._include_bodies

        async def wrapped_aiter_raw(*args, **kwargs) -> AsyncIterator[bytes]:
            response.extensions["_llm_trace_iter_started"] = True
            total: int = 0
            body_buf: Optional[bytearray] = bytearray() if include_bodies else None
            try:
                async for chunk in original_aiter_raw(*args, **kwargs):
                    total += len(chunk)
                    if include_chunks:
                        cls._emit(
                            "http_llm_chunk",
                            attempt_id=attempt_id,
                            chunk_bytes=len(chunk),
                            total_bytes=total,
                            since_out_ms=round(
                                (time.monotonic_ns() - start_ns) / 1e6, 3),
                        )
                    if body_buf is not None:
                        # Cap the captured body to keep log lines bounded.
                        if len(body_buf) < 65536:
                            body_buf.extend(chunk[: 65536 - len(body_buf)])
                    yield chunk
                if body_buf is not None:
                    response.extensions["_llm_trace_body_buf"] = bytes(body_buf)
                emit_end("stream_complete", total)
            except GeneratorExit:
                if body_buf is not None:
                    response.extensions["_llm_trace_body_buf"] = bytes(body_buf)
                emit_end("stream_generator_exit", total)
                raise
            except BaseException as exc:  # pylint: disable=broad-exception-caught
                if body_buf is not None:
                    response.extensions["_llm_trace_body_buf"] = bytes(body_buf)
                emit_end(f"stream_error:{type(exc).__name__}", total)
                raise

        async def wrapped_aclose() -> None:
            # aclose emits end only if the iterator never started (i.e.
            # response closed without reading the body). If the iterator
            # started, its own completion / exception path emits end --
            # aclose here would otherwise race with httpx's own aclose
            # firing mid-iteration and swallow the real stream_complete.
            if not response.extensions.get("_llm_trace_iter_started"):
                emit_end("closed_without_iteration", 0)
            await original_aclose()

        response.aiter_raw = wrapped_aiter_raw
        response.aclose = wrapped_aclose

    # -------------------------------------------------------------------
    # Emission helpers
    # -------------------------------------------------------------------

    @classmethod
    def _emit(cls, event: str, **fields: Any) -> None:
        """
        Build the event dict and log it as a single JSON line. Never
        raises: any error in formatting is swallowed so httpx traffic
        is never disrupted by tracing failures.
        """
        try:
            payload: Dict[str, Any] = {
                "event": event,
                "t_iso": datetime.datetime.utcnow().isoformat() + "Z",
                "t_ns": time.monotonic_ns(),
                "user_req_id": cls._user_req_id_var.get(),
                **fields,
            }
            cls._logger.info(json.dumps(payload, default=str))
        except Exception:  # pylint: disable=broad-exception-caught
            # Best-effort tracer must never break the request. Silent
            # swallow -- if the tracer itself is broken, the next dev
            # cycle will notice via missing events, not via failed LLM
            # traffic.
            pass

    @staticmethod
    def _infer_provider(host: Optional[str]) -> str:
        """
        Best-effort provider name from the request host. Used only as a
        readable label in log lines; unknown hosts default to "unknown".
        """
        if not host:
            return "unknown"

        normalized_host: str = host.strip().lower().rstrip(".")

        def _host_matches(domain: str) -> bool:
            return normalized_host == domain or normalized_host.endswith(f".{domain}")

        if _host_matches("openai.com") or _host_matches("openai.azure.com"):
            return "openai"
        if _host_matches("anthropic.com"):
            return "anthropic"
        if _host_matches("googleapis.com") or _host_matches("generativelanguage"):
            return "google"
        if _host_matches("amazonaws.com") or _host_matches("bedrock"):
            return "aws"
        if _host_matches("nvcf.nvidia.com") or _host_matches("integrate.api.nvidia.com"):
            return "nvidia"
        if _host_matches("cohere.ai"):
            return "cohere"
        return "unknown"

    @staticmethod
    def _safe_decode(data: bytes) -> str:
        """
        Best-effort decode of bytes for logging. Truncates at 64 KB to
        keep log lines bounded regardless of body size.
        """
        limit: int = 65536
        if len(data) > limit:
            snippet: bytes = data[:limit]
            return snippet.decode("utf-8", errors="replace") + f"...<truncated {len(data) - limit} bytes>"
        return data.decode("utf-8", errors="replace")
