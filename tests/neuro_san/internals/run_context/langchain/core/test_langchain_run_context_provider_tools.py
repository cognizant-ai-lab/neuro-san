# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT
"""Tests for provider-native tools at the LangChain agent boundary."""
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence

from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.runnables import Runnable
from pydantic import PrivateAttr

from neuro_san.internals.run_context.langchain.core.langchain_run_context import LangChainRunContext


pytestmark = [pytest.mark.non_default_llm_provider, pytest.mark.ollama]


class RecordingFakeChatModel(FakeMessagesListChatModel):
    """Fake chat model that records LangChain's tool binding."""

    _bound_tools: List[Any] = PrivateAttr(default_factory=list)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable:
        """Record tools and return the model as a bound runnable."""
        _ = kwargs
        self._bound_tools = list(tools)
        return self

    def get_bound_tools(self) -> List[Any]:
        """Return the tools passed to ``bind_tools``."""
        return self._bound_tools


class TestLangChainRunContextProviderTools(TestCase):
    """Verify provider-native dictionaries reach LangChain without mutating base tools."""

    @staticmethod
    def _make_context(
        provider_tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LangChainRunContext:
        """
        Build the minimum run context needed to exercise agent creation.

        :param provider_tools: Provider-native tool dictionaries to add to the llm_config.
        :return: A minimally configured LangChainRunContext.
        """
        context = LangChainRunContext.__new__(LangChainRunContext)
        context.llm_config = {}
        if provider_tools is not None:
            context.llm_config["provider_tools"] = provider_tools
        context.tools = [MagicMock(name="base_tool")]
        context.middleware_config = None
        context.invocation_context = MagicMock()
        context.origin = []
        context.chat_history = []
        context.capsule = MagicMock()
        context.tool_caller = MagicMock()
        context.tool_caller.get_sly_data.return_value = {}
        return context

    @patch("neuro_san.internals.run_context.langchain.core.langchain_run_context.MiddlewareFactory")
    @patch("neuro_san.internals.run_context.langchain.core.langchain_run_context.create_agent")
    def test_create_agent_appends_provider_tools(
        self, create_agent_mock: MagicMock, middleware_factory_mock: MagicMock
    ) -> None:
        """Provider dictionaries are appended only for LangChain agent creation."""
        provider_tool = {"type": "web_search"}
        context = self._make_context([provider_tool])
        original_tools = list(context.tools)
        middleware_factory_mock.return_value.create_agent_middleware.return_value = ([], None)

        context.create_agent("instructions", MagicMock())

        self.assertEqual(original_tools + [provider_tool], create_agent_mock.call_args.kwargs["tools"])
        self.assertEqual(original_tools, context.tools)

    @patch("neuro_san.internals.run_context.langchain.core.langchain_run_context.MiddlewareFactory")
    @patch("neuro_san.internals.run_context.langchain.core.langchain_run_context.create_agent")
    def test_create_agent_without_provider_tools_uses_base_tools(
        self, create_agent_mock: MagicMock, middleware_factory_mock: MagicMock
    ) -> None:
        """An absent provider_tools key preserves the existing tool list."""
        context = self._make_context()
        middleware_factory_mock.return_value.create_agent_middleware.return_value = ([], None)

        context.create_agent("instructions", MagicMock())

        self.assertEqual(context.tools, create_agent_mock.call_args.kwargs["tools"])

    @patch("neuro_san.internals.run_context.langchain.core.langchain_run_context.MiddlewareFactory")
    def test_real_create_agent_binds_provider_tool(self, middleware_factory_mock: MagicMock) -> None:
        """The real LangChain factory binds provider dictionaries to the model."""
        provider_tool = {"type": "web_search"}
        context = self._make_context([provider_tool])
        context.tools = []
        middleware_factory_mock.return_value.create_agent_middleware.return_value = ([], None)
        model = RecordingFakeChatModel(responses=[AIMessage(content="done")])

        agent = context.create_agent("instructions", model)
        agent.invoke({"messages": [HumanMessage(content="search")]})

        self.assertIsNotNone(agent)
        self.assertEqual([provider_tool], model.get_bound_tools())
