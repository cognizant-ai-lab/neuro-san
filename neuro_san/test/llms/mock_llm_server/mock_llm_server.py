
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
Standalone HTTP service that mimics the OpenAI Chat Completions API for
load-testing neuro-san without incurring real LLM token costs.

Exposes:
    POST /v1/chat/completions   (OpenAI-compatible; honors stream=true via SSE)
    GET  /v1/models             (lists the configured mock model)
    GET  /healthz               (liveness probe)

Wire it into a `.hocon` agent network exactly like a real OpenAI endpoint:

    llm_config {
        class = "openai"
        model_name = "mock-model"
        openai_api_base = "http://localhost:8888/v1"
        openai_api_key = "not-needed"
    }
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from typing import List
from typing import Optional

import tornado.web

from neuro_san.test.llms.mock_llm_server.chat_completions_handler import ChatCompletionsHandler
from neuro_san.test.llms.mock_llm_server.health_handler import HealthHandler
from neuro_san.test.llms.mock_llm_server.mock_state import MockState
from neuro_san.test.llms.mock_llm_server.models_handler import ModelsHandler


class MockLlmServer:
    """
    Entry point that wires the mock LLM HTTP service together: parses CLI
    flags, constructs the shared MockState, builds the Tornado application
    with the three handlers, and runs the asyncio event loop.
    """

    @staticmethod
    def build_app(state: MockState) -> tornado.web.Application:
        """Construct the Tornado Application with all routes wired up."""
        return tornado.web.Application(
            [
                (r"/v1/chat/completions", ChatCompletionsHandler, {"state": state}),
                (r"/v1/models", ModelsHandler, {"state": state}),
                (r"/healthz", HealthHandler),
            ]
        )

    @staticmethod
    def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
        """Parse CLI arguments for the mock LLM server."""
        parser = argparse.ArgumentParser(description="Mock OpenAI-compatible LLM server")
        parser.add_argument("--host", default="localhost", help="Bind host (default: localhost)")
        parser.add_argument("--port", type=int, default=8888, help="Bind port (default: 8888)")
        parser.add_argument(
            "--model-name",
            default="mock-model",
            help="Model id reported by /v1/models and echoed in responses",
        )
        parser.add_argument(
            "--min-latency", type=float, default=0.1, help="Minimum simulated latency in seconds"
        )
        parser.add_argument(
            "--max-latency", type=float, default=1.5, help="Maximum simulated latency in seconds"
        )
        parser.add_argument(
            "--stream-token-delay",
            type=float,
            default=0.02,
            help="Delay between streamed tokens in seconds (text path only)",
        )
        parser.add_argument(
            "--responses-file",
            default=None,
            help="Path to a JSON file containing an array of canned response strings",
        )
        return parser.parse_args(argv)

    @classmethod
    async def run(cls, args: argparse.Namespace) -> None:
        """Build the app, start listening, and wait forever."""
        state = MockState(
            responses=MockState.load_responses(args.responses_file),
            min_latency=args.min_latency,
            max_latency=args.max_latency,
            model_name=args.model_name,
            stream_token_delay=args.stream_token_delay,
        )
        app = cls.build_app(state)
        app.listen(args.port, address=args.host)
        logging.info(
            "mock-llm listening on http://%s:%d (model=%s, responses=%d, latency=%.2f-%.2fs)",
            args.host,
            args.port,
            state.model_name,
            len(state.responses),
            state.min_latency,
            state.max_latency,
        )
        await asyncio.Event().wait()

    @classmethod
    def main(cls, argv: Optional[List[str]] = None) -> None:
        """CLI entry point: configure logging, parse args, run until interrupted."""
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        args = cls.parse_args(argv)
        # Clamp latencies and delay to valid values: non-negative, and max >= min.
        args.min_latency = max(0.0, args.min_latency)
        args.max_latency = max(args.min_latency, args.max_latency)
        args.stream_token_delay = max(0.0, args.stream_token_delay)
        try:
            asyncio.run(cls.run(args))
        except KeyboardInterrupt:
            logging.info("mock-llm shutting down")


if __name__ == "__main__":
    MockLlmServer.main()
