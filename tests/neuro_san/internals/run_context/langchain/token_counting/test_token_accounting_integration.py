
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

import asyncio

from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import pytest

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import ChatResult

from neuro_san.internals.run_context.langchain.token_counting.langchain_token_counter import LangChainTokenCounter
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import LlmTokenCallbackHandler
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import llm_token_callback_var

INPUT_TOKENS: int = 10
OUTPUT_TOKENS: int = 5
TOTAL_TOKENS: int = INPUT_TOKENS + OUTPUT_TOKENS
MODEL_NAME: str = "fake-model"


class FakeUsageChatModel(BaseChatModel):
    """
    Minimal chat model that reports usage_metadata like a real provider would,
    so the real langchain callback machinery (configure hook, contexts, event
    dispatch) can be exercised without any network access.
    """

    @property
    def _llm_type(self) -> str:
        return "fake-usage-chat-model"

    # pylint: disable=unused-argument
    def _generate(self, messages: List[BaseMessage],
                  stop: Optional[List[str]] = None,
                  run_manager: Optional[CallbackManagerForLLMRun] = None,
                  **kwargs: Any) -> ChatResult:
        message = AIMessage(
            content="ok",
            usage_metadata={
                "input_tokens": INPUT_TOKENS,
                "output_tokens": OUTPUT_TOKENS,
                "total_tokens": TOTAL_TOKENS,
            },
            response_metadata={"model_name": MODEL_NAME},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class FakeAsyncioExecutor:
    """
    Stand-in for leaf_common's AsyncioExecutor that schedules on the running loop.
    Like the real thing when called from within its own event loop, the created
    task inherits the caller's (copied) contextvars Context.
    """

    # pylint: disable=unused-argument
    def create_task(self, awaitable, submitter_id: str) -> asyncio.Task:
        """Wrap the awaitable in a Task on the current event loop."""
        return asyncio.get_running_loop().create_task(awaitable)


class FakeInvocationContext:
    """
    Just enough InvocationContext for LangChainTokenCounter.count_tokens()/report().
    A plain class (not a Mock) because it is consulted from multiple contextvars
    Contexts.
    """

    class _FakeLlmFactory:
        # Zero prices keep calculate_token_costs() from logging warnings.
        llm_infos: Dict[str, Any] = {
            MODEL_NAME: {
                "price_per_1k_input_tokens": 0.0,
                "price_per_1k_output_tokens": 0.0,
            }
        }

    def __init__(self, request_reporting: Dict[str, Any] = None, cloned: bool = False):
        # Like SessionInvocationContext.safe_shallow_copy(), a clone for a
        # same-server external network shares the original's request_reporting.
        self.request_reporting: Dict[str, Any] = \
            request_reporting if request_reporting is not None else {}
        self.cloned: bool = cloned
        self.llm_factory = self._FakeLlmFactory()
        self.executor = FakeAsyncioExecutor()

    def get_request_reporting(self) -> Dict[str, Any]:
        """:return: The request reporting dictionary"""
        return self.request_reporting

    def get_llm_factory(self):
        """:return: The llm factory carrying llm_infos"""
        return self.llm_factory

    def get_asyncio_executor(self) -> FakeAsyncioExecutor:
        """:return: The executor used by count_tokens to run the awaitable"""
        return self.executor

    def is_cloned(self) -> bool:
        """:return: True for the clone backing an external network's direct session"""
        return self.cloned


class TestNestedTokenAccounting:
    """
    End-to-end test of the token accounting invariants through real langchain
    event dispatch, mirroring how agents nest in production:

    * An agent's handler hears downstream agents' LLM calls (callback inheritance),
      so its scalar totals are cumulative over its subtree - the per-agent
      accounting a front man reports covers the whole request.
    * request_reporting accumulates each agent's own calls exactly once, so the
      request-level totals match the front man's subtree totals instead of
      multiply-counting nested agents (the pre-fix behavior).
    * The "main_network" breakdown covers only the main network's agents, while
      the top-level totals also include same-server external networks.
    """

    # A test this end-to-end legitimately needs a handful of actors and captures.
    # pylint: disable=too-many-locals
    @pytest.mark.asyncio
    async def test_nested_agents_count_each_llm_call_exactly_once(self):
        """
        Three count_tokens() scopes with one LLM call each, shaped like a
        passthrough network: a front man, an internal downstream agent, and an
        external network's front man reached via a direct session.
        """
        invocation_context = FakeInvocationContext()
        model = FakeUsageChatModel()

        outer_origin = [{"tool": "front_man", "instantiation_index": 0}]
        inner_origin = outer_origin + [{"tool": "inner_agent", "instantiation_index": 0}]

        # Handlers are created inside count_tokens(); capture them for assertions.
        captured: Dict[str, LlmTokenCallbackHandler] = {}

        # An external network invoked through a direct session runs on a cloned
        # invocation context that shares request_reporting with the original.
        external_context = FakeInvocationContext(
            request_reporting=invocation_context.get_request_reporting(), cloned=True)
        external_origin = [{"tool": "external_front_man", "instantiation_index": 0}]

        async def downstream_body(inherited_callbacks: List[LlmTokenCallbackHandler]):
            # Passing the outer handler explicitly stands in for langchain's
            # inheritable-callback propagation in the real agent stack, where
            # RunContextRunnable.run_it() merges the ambient parent config.
            await model.ainvoke("2 + 2?", config={"callbacks": inherited_callbacks})

        async def inner_body(inherited_callbacks: List[LlmTokenCallbackHandler]):
            captured["inner"] = llm_token_callback_var.get()
            await downstream_body(inherited_callbacks)

        async def external_body(inherited_callbacks: List[LlmTokenCallbackHandler]):
            captured["external"] = llm_token_callback_var.get()
            await downstream_body(inherited_callbacks)

        async def outer_body():
            outer_handler: LlmTokenCallbackHandler = llm_token_callback_var.get()
            captured["outer"] = outer_handler

            # The outer agent's own LLM call.
            await model.ainvoke("What should I ask the inner agent?")

            # A downstream agent of the same network, with its own token counting scope.
            inner_counter = LangChainTokenCounter(model, invocation_context, None, inner_origin)
            await inner_counter.count_tokens(inner_body([outer_handler]))

            # An external network's front man invoked via a direct session.
            external_counter = LangChainTokenCounter(model, external_context, None, external_origin)
            await external_counter.count_tokens(external_body([outer_handler]))

        outer_counter = LangChainTokenCounter(model, invocation_context, None, outer_origin)
        await outer_counter.count_tokens(outer_body())

        outer_handler: LlmTokenCallbackHandler = captured["outer"]
        inner_handler: LlmTokenCallbackHandler = captured["inner"]
        external_handler: LlmTokenCallbackHandler = captured["external"]
        assert outer_handler is not None
        assert inner_handler is not None
        assert external_handler is not None
        assert len({id(outer_handler), id(inner_handler), id(external_handler)}) == 3

        # The downstream agents each saw only their own call, in both tallies.
        for handler in (inner_handler, external_handler):
            assert handler.total_tokens == TOTAL_TOKENS
            assert handler.successful_requests == 1
            handler_models = handler.models_token_dict["FakeUsageChatModel"][MODEL_NAME]
            assert handler_models["total_tokens"] == TOTAL_TOKENS

        # The outer agent's scalar totals cover its whole subtree
        # (its own call + the inner agent's + the external network's) ...
        assert outer_handler.total_tokens == 3 * TOTAL_TOKENS
        assert outer_handler.successful_requests == 3
        # ... but its per-model stats cover only its own call.
        outer_models = outer_handler.models_token_dict["FakeUsageChatModel"][MODEL_NAME]
        assert outer_models["total_tokens"] == TOTAL_TOKENS
        assert outer_models["successful_requests"] == 1

        # Request-level accounting counts each of the three LLM calls exactly once,
        # matching the front man's subtree totals.
        request_reporting: Dict[str, Any] = invocation_context.get_request_reporting()
        total_accounting: Dict[str, Any] = request_reporting["total_token_accounting"]
        assert total_accounting["total_tokens"] == 3 * TOTAL_TOKENS
        assert total_accounting["successful_requests"] == 3
        request_models = total_accounting["models"]["FakeUsageChatModel"][MODEL_NAME]
        assert request_models["total_tokens"] == 3 * TOTAL_TOKENS
        assert request_models["successful_requests"] == 3

        # "token_accounting" keeps its historically-documented meaning: the main
        # network only, excluding the external network's usage.  The server log
        # prints it before the request total.
        main_accounting: Dict[str, Any] = request_reporting["token_accounting"]
        assert main_accounting["total_tokens"] == 2 * TOTAL_TOKENS
        assert main_accounting["successful_requests"] == 2
        assert "models" not in main_accounting
        assert list(request_reporting.keys()) == \
            ["token_accounting", "total_token_accounting"]
