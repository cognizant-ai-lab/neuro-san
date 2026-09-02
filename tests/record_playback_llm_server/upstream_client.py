
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

import ssl

from typing import Callable
from typing import Dict
from typing import Optional

import tornado.httpclient

try:
    import certifi
except ImportError:
    certifi = None


class UpstreamClient:
    """
    Thin async HTTP client used in RECORD mode to forward a request to the
    real external LLM host and return (or stream) its response.

    The endpoint base URL and API key come from the server's environment
    configuration, not from the incoming request -- the incoming request's
    own Authorization header (a placeholder pointed at this proxy) is dropped
    and replaced with the real credential here.
    """

    # LLM streaming responses can run for a long time; use generous timeouts.
    DEFAULT_REQUEST_TIMEOUT_SECONDS: float = 600.0
    DEFAULT_CONNECT_TIMEOUT_SECONDS: float = 30.0
    # Tornado's default is only 10 simultaneous requests; the rest queue and can
    # time out under a load test. Default higher so concurrent recording works.
    DEFAULT_MAX_CLIENTS: int = 100

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def __init__(
        self,
        base_url: str,
        api_key: Optional[str],
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        max_clients: int = DEFAULT_MAX_CLIENTS,
    ) -> None:
        """
        :param base_url: Base URL of the external LLM host. The OpenAI-style
                         "/v1" version segment is optional: it is appended when
                         absent, so both "https://api.openai.com" and
                         "https://api.openai.com/v1" are accepted.
        :param api_key: Bearer credential for the external host. May be None
                        for hosts that do not require authentication.
        :param request_timeout: Whole-request timeout in seconds.
        :param connect_timeout: Connection timeout in seconds.
        :param max_clients: Maximum number of simultaneous in-flight requests to
                            the upstream host before further requests queue.
        """
        self.base_url: str = self._normalize_base_url(base_url)
        self.api_key: Optional[str] = api_key
        self.request_timeout: float = request_timeout
        self.connect_timeout: float = connect_timeout
        self.max_clients: int = max_clients
        # force_instance=True gives this client its own dedicated connection pool
        # with the requested max_clients, rather than the shared per-loop singleton
        # whose max_clients would otherwise be fixed by whoever created it first.
        self.client: tornado.httpclient.AsyncHTTPClient = \
            tornado.httpclient.AsyncHTTPClient(force_instance=True, max_clients=max_clients)
        self.ssl_context: ssl.SSLContext = self._build_ssl_context()

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """
        Normalize the upstream base URL: strip a trailing slash and append the
        OpenAI-style "/v1" version segment when it is absent. This lets callers
        pass either "https://host" or "https://host/v1"; both resolve to the
        same "https://host/v1". A URL that already ends in "/v1" is left as-is.
        :param base_url: The configured base URL (may be empty/None).
        :return: The normalized base URL.
        """
        if not base_url:
            return base_url
        normalized: str = base_url.rstrip("/")
        if not normalized.endswith("/v1"):
            normalized = f"{normalized}/v1"
        return normalized

    @staticmethod
    def _build_ssl_context() -> ssl.SSLContext:
        """
        Build the TLS context for outbound HTTPS. Tornado otherwise trusts the
        OS/OpenSSL default CA store, which on some platforms (notably macOS
        python.org builds) is empty and fails to verify hosts fronted by public
        CAs. Anchoring to the certifi bundle -- the same one the OpenAI/httpx
        SDKs use -- makes verification behave like the real SDKs.
        """
        if certifi is not None:
            return ssl.create_default_context(cafile=certifi.where())
        return ssl.create_default_context()

    async def fetch(self, path: str, method: str, body_bytes: bytes) -> tornado.httpclient.HTTPResponse:
        """
        Forward a one-shot (non-streaming) request and return the full response.
        :param path: Upstream sub-path, e.g. "/chat/completions".
        :param method: HTTP method.
        :param body_bytes: Raw request body (ignored for GET).
        :return: The tornado HTTPResponse (errors are captured, not raised).
        """
        request: tornado.httpclient.HTTPRequest = self._build_request(path, method, body_bytes, stream=False)
        # raise_error=False: capture non-2xx responses instead of raising, so
        # failures can be recorded and replayed just like successful responses.
        return await self.client.fetch(request, raise_error=False)

    async def fetch_stream(
        self,
        path: str,
        method: str,
        body_bytes: bytes,
        on_chunk: Callable[[bytes], None],
        on_header: Optional[Callable[[str], None]] = None,
    ) -> tornado.httpclient.HTTPResponse:
        """
        Forward a streaming request, invoking on_chunk for each received byte
        chunk as it arrives, and return the completed response.
        :param path: Upstream sub-path, e.g. "/chat/completions".
        :param method: HTTP method.
        :param body_bytes: Raw request body (ignored for GET).
        :param on_chunk: Synchronous callback invoked with each raw byte chunk.
        :param on_header: Optional callback invoked with each response header
                          line (status line included) BEFORE any body chunk, so
                          the caller can learn the upstream status/content-type
                          before writing a response.
        :return: The tornado HTTPResponse (its body is empty when streaming).
        """
        request: tornado.httpclient.HTTPRequest = self._build_request(
            path, method, body_bytes, stream=True,
            streaming_callback=on_chunk, header_callback=on_header)
        return await self.client.fetch(request, raise_error=False)

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def _build_request(
        self,
        path: str,
        method: str,
        body_bytes: bytes,
        stream: bool,
        streaming_callback: Optional[Callable[[bytes], None]] = None,
        header_callback: Optional[Callable[[str], None]] = None,
    ) -> tornado.httpclient.HTTPRequest:
        """Construct the HTTPRequest for the external host."""
        return tornado.httpclient.HTTPRequest(
            url=f"{self.base_url}{path}",
            method=method.upper(),
            headers=self._headers(stream),
            body=body_bytes if method.upper() != "GET" else None,
            request_timeout=self.request_timeout,
            connect_timeout=self.connect_timeout,
            streaming_callback=streaming_callback,
            header_callback=header_callback,
            # ssl_options is used only for https URLs; ignored for plain http.
            ssl_options=self.ssl_context,
        )

    def _headers(self, stream: bool) -> Dict[str, str]:
        """Build request headers, injecting the real credential."""
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers["Accept"] = "text/event-stream" if stream else "application/json"
        return headers
