
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

from unittest import TestCase
import pytest

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import LLMResult

from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import LlmTokenCallbackHandler

from tests.neuro_san.internals.run_context.langchain.token_counting.owning_agent_scope import owning_agent_scope


class TestExclusiveModelAttribution(TestCase):
    """
    Test cases for the own-call vs downstream-call attribution in LlmTokenCallbackHandler.

    Handlers are inheritable langchain callbacks, so an agent's handler also receives
    events for LLM calls made by downstream agents.  Those events must update the
    scalar subtree totals but NOT models_token_dict, so that merging every agent's
    models_token_dict into the request-wide accounting counts each call exactly once.
    """

    CHAT_MODEL_START_SERIALIZED = {"id": ["langchain", "chat_models", "openai", "ChatOpenAI"]}

    def _make_result(self) -> LLMResult:
        """Build an LLMResult wrapping a single AIMessage with usage metadata."""
        message = AIMessage(
            content="an answer",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            response_metadata={"model_name": "gpt-4"},
        )
        return LLMResult(generations=[[ChatGeneration(message=message)]])

    @pytest.mark.asyncio
    async def test_own_call_updates_models_and_scalars(self):
        """An LLM call belonging to this handler's own agent updates both tallies."""
        handler = LlmTokenCallbackHandler(llm_infos={})
        with owning_agent_scope(handler):
            await handler.on_chat_model_start(self.CHAT_MODEL_START_SERIALIZED, [])
            await handler.on_llm_end(self._make_result())

        assert handler.total_tokens == 15
        assert handler.successful_requests == 1
        assert handler.models_token_dict["openai"]["gpt-4"]["total_tokens"] == 15
        assert handler.models_token_dict["openai"]["gpt-4"]["successful_requests"] == 1

    @pytest.mark.asyncio
    async def test_downstream_call_updates_scalars_only(self):
        """
        A downstream agent's LLM call updates the subtree scalars of an ancestor
        handler, but not its per-model (exclusive) stats.
        """
        ancestor_handler = LlmTokenCallbackHandler(llm_infos={})
        downstream_handler = LlmTokenCallbackHandler(llm_infos={})

        # At event time, the var holds the handler of the agent that owns the call:
        # the downstream one.  The ancestor hears the same events through callback
        # inheritance.
        with owning_agent_scope(downstream_handler):
            for handler in (downstream_handler, ancestor_handler):
                await handler.on_chat_model_start(self.CHAT_MODEL_START_SERIALIZED, [])
                await handler.on_llm_end(self._make_result())

        # The owning agent counts the call in both tallies.
        assert downstream_handler.total_tokens == 15
        assert downstream_handler.models_token_dict["openai"]["gpt-4"]["total_tokens"] == 15

        # The ancestor's subtree totals include the downstream call...
        assert ancestor_handler.total_tokens == 15
        assert ancestor_handler.successful_requests == 1
        # ... but its per-model stats do not: the call is not its own.
        assert not ancestor_handler.models_token_dict
        # And its per-call timer state was never touched.
        assert ancestor_handler.start_time is None

    @pytest.mark.asyncio
    async def test_call_outside_any_agent_scope_updates_scalars_only(self):
        """With no owning agent scope at all, treat the call as not our own."""
        handler = LlmTokenCallbackHandler(llm_infos={})

        await handler.on_chat_model_start(self.CHAT_MODEL_START_SERIALIZED, [])
        await handler.on_llm_end(self._make_result())

        assert handler.total_tokens == 15
        assert not handler.models_token_dict
