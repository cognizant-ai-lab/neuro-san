
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
Standalone OpenAI-compatible HTTP proxy for neuro-san that RECORDS a session
against a real external LLM host and PLAYS it back offline -- for free and
deterministically.

Modes:
    record    -- forward every request to the external host (endpoint + key
                 from environment variables), relay the real response back to
                 neuro-san, and tee it into a cassette file on disk.
    playback  -- serve responses from the cassette by matching the canonical
                 request signature. No network, no tokens, no cost. A request
                 with no recorded match fails hard with HTTP 504.
    hybrid    -- like playback, but a cache miss falls through to the real host
                 (when one is configured), records the result into the current
                 cassette, and returns it -- a self-healing cassette. With no
                 upstream configured, a miss behaves like plain playback (504).

Endpoints (OpenAI wire-compatible):
    POST /v1/chat/completions   (honors stream=true via SSE)
    GET  /v1/models
    GET  /healthz               (liveness probe)

External LLM host (record mode, and hybrid-mode misses) is configured via
environment variables:
    RECORD_PLAYBACK_UPSTREAM_BASE_URL   e.g. "https://api.openai.com/v1"
    RECORD_PLAYBACK_UPSTREAM_API_KEY    bearer credential for that host

Point a neuro-san agent network at this proxy exactly like a real endpoint:

    llm_config {
        class = "openai"
        model_name = "gpt-4.1"
        openai_api_base = "http://localhost:8899/v1"
        openai_api_key = "not-needed"
    }
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os

from typing import List
from typing import Optional

import tornado.web

from tests.record_playback_llm_server.cassette import Cassette
from tests.record_playback_llm_server.chat_completions_handler import ChatCompletionsHandler
from tests.record_playback_llm_server.health_handler import HealthHandler
from tests.record_playback_llm_server.playback_delay import PlaybackDelay
from tests.record_playback_llm_server.models_handler import ModelsHandler
from tests.record_playback_llm_server.proxy_state import ProxyState
from tests.record_playback_llm_server.upstream_client import UpstreamClient


class RecordPlaybackLlmServer:
    """
    Entry point that wires the record/playback proxy together: parses CLI
    flags, reads the external-host configuration from the environment,
    constructs the shared ProxyState, builds the Tornado application, and
    runs the asyncio event loop.
    """

    ENV_UPSTREAM_BASE_URL: str = "RECORD_PLAYBACK_UPSTREAM_BASE_URL"
    ENV_UPSTREAM_API_KEY: str = "RECORD_PLAYBACK_UPSTREAM_API_KEY"
    ENV_UPSTREAM_REQUEST_TIMEOUT: str = "RECORD_PLAYBACK_UPSTREAM_REQUEST_TIMEOUT_SECONDS"
    ENV_UPSTREAM_CONNECT_TIMEOUT: str = "RECORD_PLAYBACK_UPSTREAM_CONNECT_TIMEOUT_SECONDS"
    ENV_UPSTREAM_MAX_CLIENTS: str = "RECORD_PLAYBACK_UPSTREAM_MAX_CLIENTS"

    DEFAULT_PORT: int = 8899
    DEFAULT_CASSETTE: str = "./llm_cassette.json"

    @staticmethod
    def build_app(state: ProxyState) -> tornado.web.Application:
        """Construct the Tornado Application with all routes wired up."""
        return tornado.web.Application(
            [
                (r"/v1/chat/completions", ChatCompletionsHandler,
                 {"state": state, "upstream_path": "/chat/completions"}),
                (r"/v1/models", ModelsHandler,
                 {"state": state, "upstream_path": "/models"}),
                (r"/healthz", HealthHandler),
            ]
        )

    @staticmethod
    def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
        """Parse CLI arguments for the record/playback proxy server."""
        parser = argparse.ArgumentParser(
            description="Record/playback OpenAI-compatible LLM proxy for neuro-san")
        parser.add_argument("--host", default="localhost", help="Bind host (default: localhost)")
        parser.add_argument("--port", type=int, default=RecordPlaybackLlmServer.DEFAULT_PORT,
                            help=f"Bind port (default: {RecordPlaybackLlmServer.DEFAULT_PORT})")
        parser.add_argument(
            "--mode", required=True,
            choices=[ProxyState.MODE_RECORD, ProxyState.MODE_PLAYBACK, ProxyState.MODE_HYBRID],
            help="record: forward to the real host and store; playback: serve from cassette (504 on miss); "
                 "hybrid: playback, but on a miss forward to the real host (if configured) and record it")
        parser.add_argument("--cassette", default=RecordPlaybackLlmServer.DEFAULT_CASSETTE,
                            help="Path to the cassette JSON file "
                                 f"(default: {RecordPlaybackLlmServer.DEFAULT_CASSETTE})")
        parser.add_argument("--multi-response", action="store_true",
                            help="record/hybrid: save every distinct response per request; "
                                 "playback: serve them round-robin")
        parser.add_argument("--stream-replay-delay", type=float, default=0.0,
                            help="Seconds between streamed SSE frames during playback (default: 0.0)")
        parser.add_argument("--delay-mode", default=PlaybackDelay.MODE_NONE, choices=PlaybackDelay.ALL_MODES,
                            help="Up-front per-response delay before serving a cache hit: none (default); "
                                 "recorded (each response's own recorded latency); fixed (--delay-seconds); "
                                 "random (uniform in [--delay-min, --delay-max])")
        parser.add_argument("--delay-seconds", type=float, default=0.0,
                            help="Delay in seconds for --delay-mode fixed (default: 0.0)")
        parser.add_argument("--delay-min", type=float, default=0.0,
                            help="Lower bound in seconds for --delay-mode random (default: 0.0)")
        parser.add_argument("--delay-max", type=float, default=0.0,
                            help="Upper bound in seconds for --delay-mode random (default: 0.0)")
        return parser.parse_args(argv)

    @classmethod
    def build_state(cls, args: argparse.Namespace) -> ProxyState:
        """
        Build the ProxyState from parsed args and the environment. Exits with a
        clear error if record mode is missing its required upstream base URL.
        """
        cassette = Cassette(args.cassette, args.multi_response)
        upstream: Optional[UpstreamClient] = None

        if args.mode == ProxyState.MODE_RECORD:
            # Record must forward every request; an upstream is mandatory.
            upstream = cls._build_upstream(required=True)
        elif args.mode == ProxyState.MODE_HYBRID:
            # Hybrid forwards only on a cache miss; an upstream is optional.
            # Without upstream configured, a cache miss behaves like plain playback (code 504).
            upstream = cls._build_upstream(required=False)
            if upstream is None:
                logging.warning("hybrid mode has no %s set; cache misses will return 504 like plain playback",
                                cls.ENV_UPSTREAM_BASE_URL)
        else:
            if not os.path.exists(args.cassette):
                logging.warning("playback cassette %s does not exist yet; all requests will 504 until recorded",
                                args.cassette)

        if args.mode == ProxyState.MODE_RECORD and args.delay_mode != PlaybackDelay.MODE_NONE:
            logging.warning("--delay-mode is ignored in record mode (it applies when serving cache hits)")

        return ProxyState(
            mode=args.mode,
            cassette=cassette,
            upstream=upstream,
            stream_replay_delay=max(0.0, args.stream_replay_delay),
            multi_response=args.multi_response,
            playback_delay=cls._build_playback_delay(args),
        )

    @staticmethod
    def _build_playback_delay(args: argparse.Namespace) -> PlaybackDelay:
        """Build the PlaybackDelay policy from parsed args, validating the range."""
        min_seconds: float = max(0.0, args.delay_min)
        max_seconds: float = max(min_seconds, args.delay_max)
        if args.delay_mode == PlaybackDelay.MODE_RANDOM and args.delay_max < args.delay_min:
            logging.warning("--delay-max (%s) < --delay-min (%s); clamping max up to min",
                            args.delay_max, args.delay_min)
        return PlaybackDelay(
            mode=args.delay_mode,
            fixed_seconds=max(0.0, args.delay_seconds),
            min_seconds=min_seconds,
            max_seconds=max_seconds,
        )

    @classmethod
    def _build_upstream(cls, required: bool) -> Optional[UpstreamClient]:
        """
        Construct the UpstreamClient from environment variables.
        :param required: When True (record mode) a missing base URL is a fatal
                         error; when False (hybrid mode) it returns None.
        """
        base_url: str = os.environ.get(cls.ENV_UPSTREAM_BASE_URL, "").strip()
        api_key: str = os.environ.get(cls.ENV_UPSTREAM_API_KEY, "").strip()
        if not base_url:
            if required:
                raise SystemExit(
                    f"record mode requires the {cls.ENV_UPSTREAM_BASE_URL} environment variable "
                    "(e.g. https://api.openai.com/v1)")
            return None
        if not api_key:
            logging.warning(
                "Upstream API key is not set; forwarding requests to %s without an Authorization header",
                base_url)
        upstream = UpstreamClient(
            base_url=base_url,
            api_key=api_key or None,
            request_timeout=cls._env_float(
                cls.ENV_UPSTREAM_REQUEST_TIMEOUT, UpstreamClient.DEFAULT_REQUEST_TIMEOUT_SECONDS),
            connect_timeout=cls._env_float(
                cls.ENV_UPSTREAM_CONNECT_TIMEOUT, UpstreamClient.DEFAULT_CONNECT_TIMEOUT_SECONDS),
            max_clients=cls._env_int(
                cls.ENV_UPSTREAM_MAX_CLIENTS, UpstreamClient.DEFAULT_MAX_CLIENTS),
        )
        logging.info(
            "upstream %s (request_timeout=%.1fs connect_timeout=%.1fs max_clients=%d)",
            base_url, upstream.request_timeout, upstream.connect_timeout, upstream.max_clients)
        return upstream

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        """Read a positive float from the environment, warning and falling back on bad input."""
        raw: str = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            value: float = float(raw)
        except ValueError:
            logging.warning("invalid %s=%r; falling back to %s", name, raw, default)
            return default
        if value <= 0:
            logging.warning("%s must be > 0 (got %s); falling back to %s", name, value, default)
            return default
        return value

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        """Read a positive int from the environment, warning and falling back on bad input."""
        raw: str = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            value: int = int(raw)
        except ValueError:
            logging.warning("invalid %s=%r; falling back to %s", name, raw, default)
            return default
        if value <= 0:
            logging.warning("%s must be > 0 (got %s); falling back to %s", name, value, default)
            return default
        return value

    @classmethod
    async def run(cls, args: argparse.Namespace) -> None:
        """Build the app, start listening, and wait forever."""
        state: ProxyState = cls.build_state(args)
        app = cls.build_app(state)
        app.listen(args.port, address=args.host)
        logging.info(
            "record-playback-llm listening on http://%s:%d "
            "(mode=%s, multi_response=%s, delay_mode=%s, cassette=%s, entries=%d)",
            args.host, args.port, state.mode, state.multi_response,
            state.playback_delay.mode, args.cassette, len(state.cassette))
        await asyncio.Event().wait()

    @classmethod
    def main(cls, argv: Optional[List[str]] = None) -> None:
        """CLI entry point: configure logging, parse args, run until interrupted."""
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        args = cls.parse_args(argv)
        try:
            asyncio.run(cls.run(args))
        except KeyboardInterrupt:
            logging.info("record-playback-llm shutting down")


if __name__ == "__main__":
    RecordPlaybackLlmServer.main()
