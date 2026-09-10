
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

from time import time
import pytest

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import LLMResult

from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import LlmTokenCallbackHandler

from tests.neuro_san.internals.run_context.langchain.token_counting.owning_agent_scope import owning_agent_scope


class TestEmptyResponseTracking:
    """Test cases for the empty_responses tracking added to LlmTokenCallbackHandler."""

    @pytest.mark.parametrize("message,expected", [
        (AIMessage(content=""), True),
        (AIMessage(content="   "), True),
        (AIMessage(content="here is the answer"), False),
        (AIMessage(content=[]), True),
        (AIMessage(content=[" "]), True),
        (AIMessage(content=[{"type": "text", "text": ""}]), True),
        (AIMessage(content=[{"type": "text", "text": "   "}]), True),
        (AIMessage(content=[{"type": "text", "text": "real text"}]), False),
        (
            AIMessage(
                content="",
                tool_calls=[{"name": "search", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            False,
        ),
    ])
    def test_is_empty_response(self, message, expected):
        """A response is empty only when it carries neither content nor a tool call."""
        # pylint: disable=protected-access
        assert LlmTokenCallbackHandler._is_empty_response(message) is expected

    def _make_result(self, content, tool_calls=None) -> LLMResult:
        """Build an LLMResult wrapping a single AIMessage with usage metadata."""
        message = AIMessage(
            content=content,
            tool_calls=tool_calls or [],
            usage_metadata={"input_tokens": 10, "output_tokens": 0, "total_tokens": 10},
            response_metadata={"model_name": "gpt-oss:20B"},
        )
        return LLMResult(generations=[[ChatGeneration(message=message)]])

    def _make_handler(self) -> LlmTokenCallbackHandler:
        handler = LlmTokenCallbackHandler(llm_infos={})
        handler.provider_class = "ollama"
        handler.models_token_dict = {"ollama": {}}
        handler.start_time = time()
        return handler

    @pytest.mark.asyncio
    async def test_on_llm_end_counts_empty_response(self):
        """An empty response counts as a successful request AND an empty one."""
        handler = self._make_handler()
        with owning_agent_scope(handler):
            await handler.on_llm_end(self._make_result(content=""))
        assert handler.successful_requests == 1
        assert handler.empty_responses == 1
        assert handler.models_token_dict["ollama"]["gpt-oss:20B"]["empty_responses"] == 1

    @pytest.mark.asyncio
    async def test_on_llm_end_does_not_count_nonempty_response(self):
        """A response with content is a successful request but not an empty one."""
        handler = self._make_handler()
        with owning_agent_scope(handler):
            await handler.on_llm_end(self._make_result(content="a real answer"))
        assert handler.successful_requests == 1
        assert handler.empty_responses == 0
        assert handler.models_token_dict["ollama"]["gpt-oss:20B"]["empty_responses"] == 0
