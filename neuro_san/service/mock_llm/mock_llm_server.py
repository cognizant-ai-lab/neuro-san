
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

The handler reproduces MockChatModel's logic:
- If the request has tools and the message history does NOT yet contain a
  tool result, return a tool_call to a randomly chosen tool with minimal
  valid arguments.
- Otherwise return canned text from the configured response list.
- Random latency is applied to emulate real LLM response times.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import time
import uuid

from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import tornado.ioloop
import tornado.iostream
import tornado.web


DEFAULT_RESPONSES: List[str] = [
    "Based on my analysis, the answer to your question is 42.",
    "I have reviewed the available information and here is my assessment: "
    "everything looks good and is proceeding as expected.",
    "After careful consideration, I recommend proceeding with the proposed approach. "
    "The benefits outweigh the potential risks.",
    "Here is a summary of the key findings: the data indicates positive trends "
    "across all measured dimensions.",
    "Thank you for your question. The short answer is yes, and here are the details "
    "to support that conclusion.",
    "I have completed the requested task. All items have been processed successfully "
    "and the results are ready for your review.",
    "The analysis is complete. Three main factors contribute to the observed outcome: "
    "timing, resource allocation, and coordination.",
    "Based on the information provided, I suggest the following course of action: "
    "prioritize the critical items first, then address the remaining tasks in order.",
]


def _default_value_for_schema(schema: Dict[str, Any]) -> Any:
    """Generate a minimal default value that satisfies a JSON Schema type."""
    schema_type = schema.get("type", "string")
    if schema_type == "string":
        enum = schema.get("enum")
        if enum:
            return enum[0]
        return "test"
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return True
    if schema_type == "array":
        return []
    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        obj = {}
        for prop_name in required:
            prop_schema = properties.get(prop_name, {"type": "string"})
            obj[prop_name] = _default_value_for_schema(prop_schema)
        return obj
    return "test"


def _generate_tool_args(tool_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Generate minimal arguments that satisfy a tool's parameter schema."""
    parameters = tool_schema.get("parameters", {})
    properties = parameters.get("properties", {})
    required = parameters.get("required", list(properties.keys()))
    args = {}
    for param_name in required:
        param_schema = properties.get(param_name, {"type": "string"})
        args[param_name] = _default_value_for_schema(param_schema)
    return args


def _has_tool_results(messages: List[Dict[str, Any]]) -> bool:
    """Whether the message history already contains tool-call results."""
    return any(m.get("role") == "tool" for m in messages)


class MockState:
    """Process-wide configuration and rotating-response counter."""

    def __init__(
        self,
        responses: List[str],
        min_latency: float,
        max_latency: float,
        model_name: str,
        stream_token_delay: float,
    ) -> None:
        self.responses = responses
        self.min_latency = min_latency
        self.max_latency = max_latency
        self.model_name = model_name
        self.stream_token_delay = stream_token_delay
        self._counter = 0

    def next_response(self) -> str:
        text = self.responses[self._counter % len(self.responses)]
        self._counter += 1
        return text

    async def sleep(self) -> None:
        delay = random.uniform(self.min_latency, self.max_latency)
        await asyncio.sleep(delay)


class ChatCompletionsHandler(tornado.web.RequestHandler):
    """Implements POST /v1/chat/completions in OpenAI-compatible form."""

    def initialize(self, state: MockState) -> None:
        self.state = state

    async def post(self) -> None:
        try:
            body: Dict[str, Any] = json.loads(self.request.body or b"{}")
        except json.JSONDecodeError as exc:
            self.set_status(400)
            self.write({"error": {"message": f"invalid JSON body: {exc}"}})
            return

        messages: List[Dict[str, Any]] = body.get("messages", []) or []
        tools: List[Dict[str, Any]] = body.get("tools", []) or []
        requested_model: str = body.get("model") or self.state.model_name
        stream: bool = bool(body.get("stream"))

        await self.state.sleep()

        if stream:
            await self._stream(requested_model, messages, tools)
            return

        if tools and not _has_tool_results(messages):
            message_payload, finish_reason = self._tool_call_response(tools)
        else:
            message_payload = {"role": "assistant", "content": self.state.next_response()}
            finish_reason = "stop"

        self.write(self._chat_completion_envelope(requested_model, message_payload, finish_reason))

    @staticmethod
    def _tool_call_response(tools: List[Dict[str, Any]]) -> tuple[Dict[str, Any], str]:
        tool = random.choice(tools)
        # OpenAI tool spec: {"type":"function","function":{"name":..., "parameters":...}}
        func_info = tool.get("function", tool)
        tool_name = func_info.get("name", "unknown_tool")
        args = _generate_tool_args(func_info)
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_{uuid.uuid4().hex[:24]}",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(args),
                    },
                }
            ],
        }
        return message, "tool_calls"

    async def _stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> None:
        """Stream an OpenAI-compatible response as Server-Sent Events."""
        self.set_header("Content-Type", "text/event-stream")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("X-Accel-Buffering", "no")

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())

        def chunk(delta: Dict[str, Any], finish_reason: Optional[str] = None) -> Dict[str, Any]:
            return {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {"index": 0, "delta": delta, "finish_reason": finish_reason}
                ],
            }

        try:
            if tools and not _has_tool_results(messages):
                tool = random.choice(tools)
                func_info = tool.get("function", tool)
                tool_name = func_info.get("name", "unknown_tool")
                args_str = json.dumps(_generate_tool_args(func_info))
                tool_call_id = f"call_{uuid.uuid4().hex[:24]}"

                # Opening chunk: role + tool_call skeleton with the function name.
                await self._send_event(chunk({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "index": 0,
                        "id": tool_call_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": ""},
                    }],
                }))
                # Argument chunk: full JSON arg string in one delta. OpenAI may
                # split this across many chunks; clients concatenate them, so
                # one chunk is protocol-valid and simpler.
                await self._send_event(chunk({
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": args_str},
                    }],
                }))
                await self._send_event(chunk({}, finish_reason="tool_calls"))
            else:
                text = self.state.next_response()
                await self._send_event(chunk({"role": "assistant", "content": ""}))
                words = text.split(" ")
                for idx, word in enumerate(words):
                    token = word if idx == 0 else " " + word
                    await self._send_event(chunk({"content": token}))
                    if self.state.stream_token_delay > 0:
                        await asyncio.sleep(self.state.stream_token_delay)
                await self._send_event(chunk({}, finish_reason="stop"))

            self.write("data: [DONE]\n\n")
            await self.flush()
        except tornado.iostream.StreamClosedError:
            # Client disconnected mid-stream; nothing more to do.
            return

    async def _send_event(self, payload: Dict[str, Any]) -> None:
        self.write(f"data: {json.dumps(payload)}\n\n")
        await self.flush()

    @staticmethod
    def _chat_completion_envelope(
        model: str,
        message: Dict[str, Any],
        finish_reason: str,
    ) -> Dict[str, Any]:
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }


class ModelsHandler(tornado.web.RequestHandler):
    """Implements GET /v1/models so OpenAI-style clients can introspect."""

    def initialize(self, state: MockState) -> None:
        self.state = state

    def get(self) -> None:
        self.write(
            {
                "object": "list",
                "data": [
                    {
                        "id": self.state.model_name,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "mock",
                    }
                ],
            }
        )


class HealthHandler(tornado.web.RequestHandler):
    def get(self) -> None:
        self.write({"status": "ok"})


def _load_responses(path: Optional[str]) -> List[str]:
    if not path:
        return list(DEFAULT_RESPONSES)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not all(isinstance(s, str) for s in data):
        raise ValueError(f"{path} must contain a JSON array of strings")
    if not data:
        raise ValueError(f"{path} must contain at least one response")
    return data


def build_app(state: MockState) -> tornado.web.Application:
    return tornado.web.Application(
        [
            (r"/v1/chat/completions", ChatCompletionsHandler, {"state": state}),
            (r"/v1/models", ModelsHandler, {"state": state}),
            (r"/healthz", HealthHandler),
        ]
    )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mock OpenAI-compatible LLM server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
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


async def _run(args: argparse.Namespace) -> None:
    state = MockState(
        responses=_load_responses(args.responses_file),
        min_latency=args.min_latency,
        max_latency=args.max_latency,
        model_name=args.model_name,
        stream_token_delay=args.stream_token_delay,
    )
    app = build_app(state)
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


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        logging.info("mock-llm shutting down")


if __name__ == "__main__":
    main()
