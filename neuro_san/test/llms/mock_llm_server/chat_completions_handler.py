
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
import html
import json
import random
import time
import uuid

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import tornado.iostream
import tornado.web

from neuro_san.test.llms.mock_llm_server.mock_state import MockState
from neuro_san.test.llms.mock_llm_server.tool_arg_generator import ToolArgGenerator


class ChatCompletionsHandler(tornado.web.RequestHandler):
    """
    Implements POST /v1/chat/completions in OpenAI-compatible form. Honors
    the `stream` flag of the request body, emitting either a single JSON
    chat completion or a Server-Sent Event stream of completion chunks.
    """

    def initialize(self, state: MockState) -> None:
        """Receive the shared MockState from the Tornado application."""
        # pylint: disable=attribute-defined-outside-init
        self.state = state

    async def post(self) -> None:
        """Handle a chat-completions request, streaming or one-shot."""
        try:
            body: Dict[str, Any] = json.loads(self.request.body or b"{}")
        except json.JSONDecodeError:
            self.set_status(400)
            self.write({"error": {"message": "invalid JSON body"}})
            return

        messages: List[Dict[str, Any]] = body.get("messages", []) or []
        tools: List[Dict[str, Any]] = body.get("tools", []) or []
        requested_model: str = body.get("model") or self.state.model_name
        stream: bool = bool(body.get("stream"))

        await self.state.sleep()

        if stream:
            await self._stream(requested_model, messages, tools)
            return

        if tools and not ToolArgGenerator.has_tool_results(messages):
            message_payload, finish_reason = self._tool_call_response(tools)
        else:
            message_payload = {"role": "assistant", "content": self.state.next_response()}
            finish_reason = "stop"

        self.write(self._chat_completion_envelope(requested_model, message_payload, finish_reason))

    @staticmethod
    def _tool_call_response(tools: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], str]:
        tool = random.choice(tools)
        # OpenAI tool spec: {"type":"function","function":{"name":..., "parameters":...}}
        func_info = tool.get("function", tool)
        tool_name = str(func_info.get("name", "unknown_tool"))
        args = ToolArgGenerator.generate_tool_args(func_info)
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

        try:
            if tools and not ToolArgGenerator.has_tool_results(messages):
                await self._stream_tool_call(completion_id, created, model, tools)
            else:
                await self._stream_text_response(completion_id, created, model)
            self.write("data: [DONE]\n\n")
            await self.flush()
        except tornado.iostream.StreamClosedError:
            # Client disconnected mid-stream; nothing more to do.
            return

    @staticmethod
    def _chunk_envelope(
        completion_id: str,
        created: int,
        model: str,
        delta: Dict[str, Any],
        finish_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build one OpenAI chat.completion.chunk envelope."""
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {"index": 0, "delta": delta, "finish_reason": finish_reason}
            ],
        }

    async def _stream_tool_call(
        self,
        completion_id: str,
        created: int,
        model: str,
        tools: List[Dict[str, Any]],
    ) -> None:
        """Stream a single tool_call across three SSE chunks."""
        tool = random.choice(tools)
        func_info = tool.get("function", tool)
        tool_name = func_info.get("name", "unknown_tool")
        args_str = json.dumps(ToolArgGenerator.generate_tool_args(func_info))
        tool_call_id = f"call_{uuid.uuid4().hex[:24]}"

        # Opening chunk: role + tool_call skeleton with the function name.
        await self._send_event(self._chunk_envelope(completion_id, created, model, {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "index": 0,
                "id": tool_call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": ""},
            }],
        }))
        # Argument chunk: full JSON arg string in one delta. OpenAI may split
        # this across many chunks; clients concatenate them, so one chunk is
        # protocol-valid and simpler.
        await self._send_event(self._chunk_envelope(completion_id, created, model, {
            "tool_calls": [{
                "index": 0,
                "function": {"arguments": args_str},
            }],
        }))
        await self._send_event(self._chunk_envelope(
            completion_id, created, model, {}, finish_reason="tool_calls"))

    async def _stream_text_response(self, completion_id: str, created: int, model: str) -> None:
        """Stream a text response one whitespace-split word per SSE chunk."""
        text = self.state.next_response()
        await self._send_event(self._chunk_envelope(
            completion_id, created, model, {"role": "assistant", "content": ""}))
        for idx, word in enumerate(text.split(" ")):
            token = word if idx == 0 else " " + word
            await self._send_event(self._chunk_envelope(
                completion_id, created, model, {"content": token}))
            if self.state.stream_token_delay > 0:
                await asyncio.sleep(self.state.stream_token_delay)
        await self._send_event(self._chunk_envelope(
            completion_id, created, model, {}, finish_reason="stop"))

    async def _send_event(self, payload: Dict[str, Any]) -> None:
        """Write one `data: {json}\\n\\n` SSE frame and flush it to the client."""
        serialized_payload = json.dumps(payload, separators=(",", ":"))
        self.write(f"data: {serialized_payload}\n\n")
        await self.flush()

    def data_received(self, chunk):
        """Required override of RequestHandler abstract method; full body comes via self.request.body."""
        return

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
            "model": str(model),
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
