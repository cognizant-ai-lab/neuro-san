
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
    record   -- forward every request to the external host (endpoint + key
                from environment variables), relay the real response back to
                neuro-san, and tee it into a cassette file on disk.
    playback -- serve responses from the cassette by matching the canonical
                request signature. No network, no tokens, no cost. A request
                with no recorded match fails hard with HTTP 504.

Endpoints (OpenAI wire-compatible):
    POST /v1/chat/completions   (honors stream=true via SSE)
    GET  /v1/models
    GET  /healthz               (liveness probe)

External LLM host (record mode) is configured via environment variables:
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
        parser.add_argument("--mode", required=True, choices=[ProxyState.MODE_RECORD, ProxyState.MODE_PLAYBACK],
                            help="record: forward to the real host and store; playback: serve from cassette")
        parser.add_argument("--cassette", default=RecordPlaybackLlmServer.DEFAULT_CASSETTE,
                            help="Path to the cassette JSON file "
                                 f"(default: {RecordPlaybackLlmServer.DEFAULT_CASSETTE})")
        parser.add_argument("--stream-replay-delay", type=float, default=0.0,
                            help="Seconds between streamed SSE frames during playback (default: 0.0)")
        return parser.parse_args(argv)

    @classmethod
    def build_state(cls, args: argparse.Namespace) -> ProxyState:
        """
        Build the ProxyState from parsed args and the environment. Exits with a
        clear error if record mode is missing its required upstream base URL.
        """
        cassette = Cassette(args.cassette)
        upstream: Optional[UpstreamClient] = None

        if args.mode == ProxyState.MODE_RECORD:
            base_url: str = os.environ.get(cls.ENV_UPSTREAM_BASE_URL, "").strip()
            api_key: str = os.environ.get(cls.ENV_UPSTREAM_API_KEY, "").strip()
            if not base_url:
                raise SystemExit(
                    f"record mode requires the {cls.ENV_UPSTREAM_BASE_URL} environment variable "
                    "(e.g. https://api.openai.com/v1)")
            if not api_key:
                logging.warning("%s is not set; forwarding requests to %s without an Authorization header",
                                cls.ENV_UPSTREAM_API_KEY, base_url)
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
        else:
            if not os.path.exists(args.cassette):
                logging.warning("playback cassette %s does not exist yet; all requests will 504 until recorded",
                                args.cassette)

        return ProxyState(
            mode=args.mode,
            cassette=cassette,
            upstream=upstream,
            stream_replay_delay=max(0.0, args.stream_replay_delay),
        )

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
            "record-playback-llm listening on http://%s:%d (mode=%s, cassette=%s, entries=%d)",
            args.host, args.port, state.mode, args.cassette, len(state.cassette))
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
