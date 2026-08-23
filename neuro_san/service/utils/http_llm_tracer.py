
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
from typing import List
from typing import Optional

import contextvars
import datetime
import functools
import json
import logging
import time
import uuid
import httpx

from leaf_common.logging.sensitive_logger import SensitiveLogger


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

    Env vars:
    AGENT_HTTP_LLM_TRACE (default "false") — master toggle. When enabled, installs the tracer on server startup.
    AGENT_HTTP_LLM_TRACE_INCLUDE_BODIES (default "false") — capture request/response bodies verbatim
            (capped at 64 KB each).
            Prompts and completions are large and often sensitive; off by default.
    AGENT_HTTP_LLM_TRACE_CHUNKS (default "false") — emit one event per received body chunk.
            Massive log volume (dozens of chunks per streaming LLM call);
            enable only when investigating inter-chunk cadence.

    ================================================================
    Coding-policy notes (per neuro-san team standards)
    ================================================================
    All helpers are class-level static or classmethods. No nested /
    embedded functions inside methods -- state that would normally live
    in closures instead lives on:
      - response.extensions[...] : per-response state (end_emitted flag,
                                   iter_started flag, saved original
                                   aiter_raw / aclose, buffered body).
      - request.extensions[...]  : per-request state (attempt_id, start_ns).
      - class attributes         : per-installation state
                                   (_original_httpx_init, _include_*, _logger).
    functools.partial is used to bind response into the response-scoped
    wrappers (_wrapped_aiter_raw, _wrapped_aclose) at assignment time.

    ================================================================
    Known limitations / future work
    ================================================================
    1. httpx transport only. Providers using non-httpx clients (notably
       AWS Bedrock via aiobotocore, and any future gRPC-based provider
       path such as Vertex AI direct) bypass this tracer. Extending to
       Bedrock requires registering hooks on botocore's event system;
       see BOTOCORE_SESSION.register('before-send.*', ...) as the
       entry point.

    2. Stream-body capture (when AGENT_HTTP_LLM_TRACE_INCLUDE_BODIES
       is enabled) truncates each body at 64 KB. Increase the cap or
       stream to a separate file if full-body capture is required.
       The truncation is intentional to keep single log lines bounded
       for downstream parsers (jq, pandas).

    3. Free-threaded Python (cpython-3.14t) compatibility: the tracer
       itself has no C dependencies and works cleanly on 3.14t. Some
       dependent packages that the neuro-san dep graph pulls in
       (notably orjson) refuse to build for the free-threaded ABI at
       the time of writing. Use a stdlib-json shim for orjson or
       wait for upstream support if running under free-threaded Python.

    4. Tornado-loop-only ContextVar propagation is guaranteed by
       Python's asyncio internals. Any future non-asyncio bridge
       (e.g., a raw threading.Thread that runs LLM calls without
       contextvars.copy_context) would drop the user_req_id and
       events would emit with user_req_id=None. Not a current concern
       for neuro-san, but flag it if such a bridge is added.

    5. Per-attempt correlation only. This tracer does not add a
       parent-span concept. Each httpx retry appears as an independent
       attempt_id under the same user_req_id; post-processing must
       infer retry chains by proximity and URL match. If tighter
       correlation becomes necessary, add an "attempt_parent_id"
       field populated from a request extension set by upstream SDK
       retry logic (where available).
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
    _sensitive_logger: Optional[SensitiveLogger] = None
    # Stash of the pre-patch httpx.AsyncClient.__init__ so the patched
    # replacement can delegate to it.
    _original_httpx_init: Optional[Callable[..., None]] = None

    # Body-capture cap. Applied both to request bodies (immediate) and
    # response bodies (accumulated during aiter_raw).
    _BODY_CAP_BYTES: int = 65536

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
        cls._sensitive_logger = SensitiveLogger(cls._logger)

        cls._original_httpx_init = httpx.AsyncClient.__init__
        # Assign the class-level replacement. staticmethod descriptor
        # resolves to the underlying function on class access, so this
        # sets AsyncClient.__init__ to a plain function that Python will
        # invoke as a bound method (with client instance as first arg).
        httpx.AsyncClient.__init__ = HttpxLlmTracer._patched_httpx_init

        cls._installed = True
        cls._logger.info(
            "HttpxLlmTracer installed (include_bodies=%s include_chunks=%s)",
            include_bodies, include_chunks)

    @staticmethod
    def _patched_httpx_init(client_self, *args, **kwargs) -> None:
        """
        Replacement for httpx.AsyncClient.__init__. Injects our
        request/response hooks alongside whatever the SDK already set.
        Delegates to the original init captured at install() time.
        """
        existing_hooks: Dict[str, list] = kwargs.pop("event_hooks", None) or {}
        merged_hooks: Dict[str, list] = dict(existing_hooks)
        merged_hooks["request"] = (
            [HttpxLlmTracer._on_request] + list(existing_hooks.get("request", []))
        )
        merged_hooks["response"] = (
            [HttpxLlmTracer._on_response] + list(existing_hooks.get("response", []))
        )
        kwargs["event_hooks"] = merged_hooks

        # install() sets _original_httpx_init BEFORE monkey-patching
        # httpx.AsyncClient.__init__ to this method, so it's guaranteed
        # non-None here. Runtime guard raises early if that invariant is
        # ever broken (e.g. someone bypassed install() and directly
        # assigned _patched_httpx_init to httpx.AsyncClient). The pylint
        # suppression on the call is because pylint's not-callable
        # checker doesn't infer callability from typing.Callable
        # annotations even after None-narrowing (known pylint limitation).
        original_init = HttpxLlmTracer._original_httpx_init
        if original_init is None:
            raise ValueError("HttpxLlmTracer.install() must be called before "
                             "httpx.AsyncClient() can be constructed")
        original_init(client_self, *args, **kwargs)  # pylint: disable=not-callable

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
        cls._wrap_response_for_end(response)

    @classmethod
    def _wrap_response_for_end(cls, response) -> None:
        """
        Replace the response's aiter_raw and aclose with class-level
        wrappers, and stash the originals + firing-state flags on
        response.extensions. Everything the wrappers need travels with
        the response object -- no closures required.

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
        # response object and is trivially inspectable in the debugger.
        response.extensions["_llm_trace_end_emitted"] = False
        response.extensions["_llm_trace_iter_started"] = False
        response.extensions["_llm_trace_original_aiter_raw"] = response.aiter_raw
        response.extensions["_llm_trace_original_aclose"] = response.aclose

        # Bind response into the class-level wrappers via functools.partial.
        # No lambdas, no nested defs -- purely composition of top-level
        # callables.
        response.aiter_raw = functools.partial(cls._wrapped_aiter_raw, response)
        response.aclose = functools.partial(cls._wrapped_aclose, response)

    # -------------------------------------------------------------------
    # Response-scoped wrappers (bound to a response via functools.partial)
    # -------------------------------------------------------------------

    @staticmethod
    async def _wrapped_aiter_raw(response, *args, **kwargs) -> AsyncIterator[bytes]:
        """
        Class-level replacement for httpx.Response.aiter_raw. Invoked via
        functools.partial(_wrapped_aiter_raw, response), so the first arg
        is the response object. Delegates to the original aiter_raw
        (stashed on response.extensions) and emits chunk / end events
        along the way.
        """
        response.extensions["_llm_trace_iter_started"] = True
        request_ext = response.request.extensions
        attempt_id: str = request_ext.get("_llm_trace_attempt_id", "unknown")
        start_ns: int = request_ext.get("_llm_trace_start_ns", time.monotonic_ns())
        original_aiter_raw: Callable = response.extensions["_llm_trace_original_aiter_raw"]
        include_chunks: bool = HttpxLlmTracer._include_chunks
        include_bodies: bool = HttpxLlmTracer._include_bodies
        body_cap: int = HttpxLlmTracer._BODY_CAP_BYTES

        total: int = 0
        body_buf: Optional[bytearray] = bytearray() if include_bodies else None
        try:
            async for chunk in original_aiter_raw(*args, **kwargs):
                total += len(chunk)
                if include_chunks:
                    HttpxLlmTracer._emit(
                        "http_llm_chunk",
                        attempt_id=attempt_id,
                        chunk_bytes=len(chunk),
                        total_bytes=total,
                        since_out_ms=round(
                            (time.monotonic_ns() - start_ns) / 1e6, 3),
                    )
                if body_buf is not None and len(body_buf) < body_cap:
                    # Cap the captured body to keep log lines bounded.
                    body_buf.extend(chunk[: body_cap - len(body_buf)])
                yield chunk
            if body_buf is not None:
                response.extensions["_llm_trace_body_buf"] = bytes(body_buf)
            HttpxLlmTracer._emit_end(response, "stream_complete", total)
        except GeneratorExit:
            if body_buf is not None:
                response.extensions["_llm_trace_body_buf"] = bytes(body_buf)
            HttpxLlmTracer._emit_end(response, "stream_generator_exit", total)
            raise
        except BaseException as exc:  # pylint: disable=broad-exception-caught
            if body_buf is not None:
                response.extensions["_llm_trace_body_buf"] = bytes(body_buf)
            HttpxLlmTracer._emit_end(response, f"stream_error:{type(exc).__name__}", total)
            raise

    @staticmethod
    async def _wrapped_aclose(response) -> None:
        """
        Class-level replacement for httpx.Response.aclose. Invoked via
        functools.partial(_wrapped_aclose, response). Emits end only when
        the wrapped iterator never started -- see _wrap_response_for_end's
        firing-rules comment for why.
        """
        if not response.extensions.get("_llm_trace_iter_started"):
            HttpxLlmTracer._emit_end(response, "closed_without_iteration", 0)
        original_aclose: Callable = response.extensions["_llm_trace_original_aclose"]
        await original_aclose()

    @staticmethod
    def _emit_end(response, reason: str, bytes_read: int) -> None:
        """
        Emit exactly-once http_llm_end for a response. Reads attempt_id
        and start_ns from response.request.extensions and any buffered
        body from response.extensions.
        """
        if response.extensions.get("_llm_trace_end_emitted"):
            return
        response.extensions["_llm_trace_end_emitted"] = True

        request_ext = response.request.extensions
        attempt_id: str = request_ext.get("_llm_trace_attempt_id", "unknown")
        start_ns: int = request_ext.get("_llm_trace_start_ns", time.monotonic_ns())
        elapsed_ms: float = (time.monotonic_ns() - start_ns) / 1e6

        fields: Dict[str, Any] = {
            "attempt_id": attempt_id,
            "elapsed_ms": round(elapsed_ms, 3),
            "reason": reason,
            "stream_bytes": bytes_read,
        }
        if HttpxLlmTracer._include_bodies:
            captured: Optional[bytes] = response.extensions.get("_llm_trace_body_buf")
            if captured is not None:
                fields["resp_body"] = HttpxLlmTracer._safe_decode(captured)
        HttpxLlmTracer._emit("http_llm_end", **fields)

    # -------------------------------------------------------------------
    # Emission + provider inference helpers
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
            cls._sensitive_logger.info(json.dumps(payload, default=str))
        except Exception:  # pylint: disable=broad-exception-caught
            # Best-effort tracer must never break the request. Silent
            # swallow -- if the tracer itself is broken, the next dev
            # cycle will notice via missing events, not via failed LLM
            # traffic.
            pass

    @staticmethod
    def _host_matches(normalized_host: str, domains: List[str]) -> bool:
        """
        Return True if the normalized host matches the domain or is a subdomain of it
        for any of the provided domains.
        Used for provider inference.
        """
        for domain in domains:
            if normalized_host == domain or normalized_host.endswith(f".{domain}"):
                return True
        return False

    @staticmethod
    def _infer_provider(host: Optional[str]) -> str:
        """
        Best-effort provider name from the request host. Used only as a
        readable label in log lines; unknown hosts default to "unknown".
        """
        # pylint: disable=too-many-return-statements
        if not host:
            return "unknown"

        normalized_host: str = host.strip().lower().rstrip(".")

        if HttpxLlmTracer._host_matches(normalized_host, ["openai.com", "openai.azure.com"]):
            return "openai"
        if HttpxLlmTracer._host_matches(normalized_host, ["anthropic.com"]):
            return "anthropic"
        if HttpxLlmTracer._host_matches(normalized_host, ["googleapis.com", "generativelanguage"]):
            return "google"
        if HttpxLlmTracer._host_matches(normalized_host, ["amazonaws.com", "bedrock"]):
            return "aws"
        if HttpxLlmTracer._host_matches(normalized_host, ["nvcf.nvidia.com", "integrate.api.nvidia.com"]):
            return "nvidia"
        if HttpxLlmTracer._host_matches(normalized_host, ["cohere.ai"]):
            return "cohere"
        return "unknown"

    @staticmethod
    def _safe_decode(data: bytes) -> str:
        """
        Best-effort decode of bytes for logging. Truncates at the class
        body cap to keep log lines bounded regardless of body size.
        """
        limit: int = HttpxLlmTracer._BODY_CAP_BYTES
        if len(data) > limit:
            snippet: bytes = data[:limit]
            return snippet.decode("utf-8", errors="replace") + f"...<truncated {len(data) - limit} bytes>"
        return data.decode("utf-8", errors="replace")
