
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

from typing import Any
from typing import Dict
from typing import List
from unittest.mock import MagicMock

import pytest

from neuro_san.internals.run_context.langchain.core.langchain_run_context import LangChainRunContext


# Both markers needed so conftest.py skips the OPENAI_API_KEY requirement:
# these tests fully mock the LLM factory, so no real provider key is required.
pytestmark = [pytest.mark.non_default_llm_provider, pytest.mark.ollama]


class TestLangChainRunContext:
    """Tests for the LangChainRunContext class."""

    @staticmethod
    def _make_run_context(llm_config: Dict[str, Any], create_llm_side_effect) -> LangChainRunContext:
        """
        Build a LangChainRunContext with the bare minimum wiring needed to exercise
        create_agent_with_fallbacks(), bypassing __init__ to avoid pulling in the
        full RunContext / invocation_context machinery.

        :param llm_config: The llm_config dict (may contain a "fallbacks" list).
        :param create_llm_side_effect: Iterable of values/exceptions for the mocked
            llm_factory.create_llm calls, one per fallback iteration.
        """
        run_context = LangChainRunContext.__new__(LangChainRunContext)
        run_context.llm_config = llm_config
        run_context.llm_resources = None

        llm_factory = MagicMock()
        llm_factory.create_llm = MagicMock(side_effect=create_llm_side_effect)

        invocation_context = MagicMock()
        invocation_context.get_llm_factory.return_value = llm_factory

        tool_caller = MagicMock()
        tool_caller.get_sly_data.return_value = {}

        run_context.invocation_context = invocation_context
        run_context.tool_caller = tool_caller

        # Replace create_agent so we don't drag in langchain's create_agent and
        # middleware machinery — calling the mock returns a Runnable-like MagicMock.
        run_context.create_agent = MagicMock()

        return run_context

    @staticmethod
    def _llm_resources_mock() -> MagicMock:
        """A stand-in for a successful LangChainLlmResources return value."""
        resources = MagicMock()
        resources.get_model.return_value = MagicMock(name="llm_model")
        return resources

    def test_failing_first_fallback_continues_to_next(self):
        """
        If create_llm raises ValueError on the first fallback, the loop should
        record the error, continue to the next fallback, and return its agent.
        """
        llm_config: Dict[str, Any] = {
            "fallbacks": [
                {"class": "anthropic", "model_name": "claude-sonnet-4-6"},
                {"class": "openai", "model_name": "gpt-5.2"},
            ]
        }
        side_effect: List[Any] = [
            ValueError("anthropic_api_key missing"),
            self._llm_resources_mock(),
        ]
        run_context = self._make_run_context(llm_config, side_effect)

        agent = run_context.create_agent_with_fallbacks("dummy instructions")

        assert agent is not None
        # Both fallbacks were attempted (the first raised, the second succeeded).
        create_llm = run_context.invocation_context.get_llm_factory().create_llm
        assert create_llm.call_count == 2
        # create_agent only got invoked once — for the successful (openai) fallback.
        assert run_context.create_agent.call_count == 1

    def test_sly_data_missing_keys_continues_to_next_fallback(self):
        """
        If a fallback reports missing sly_data keys (set return from create_llm),
        the loop should continue to the next fallback and return its agent.
        """
        llm_config: Dict[str, Any] = {
            "fallbacks": [
                {"class": "anthropic", "model_name": "claude-sonnet-4-6",
                 "anthropic_api_key": "sly_data"},
                {"class": "openai", "model_name": "gpt-5.2"},
            ]
        }
        side_effect: List[Any] = [
            {"anthropic_api_key"},
            self._llm_resources_mock(),
        ]
        run_context = self._make_run_context(llm_config, side_effect)

        agent = run_context.create_agent_with_fallbacks("dummy instructions")

        assert agent is not None
        create_llm = run_context.invocation_context.get_llm_factory().create_llm
        assert create_llm.call_count == 2
        # create_agent only got invoked once — for the successful (openai) fallback.
        assert run_context.create_agent.call_count == 1

    def test_all_fallbacks_missing_sly_data_surfaces_required_keys(self):
        """
        When every fallback reports missing sly_data keys, the final ValueError
        should list the union of required sly_data.llm_config keys under the
        appropriate section header.
        """
        llm_config: Dict[str, Any] = {
            "fallbacks": [
                {"class": "anthropic", "model_name": "claude-sonnet-4-6",
                 "anthropic_api_key": "sly_data"},
                {"class": "openai", "model_name": "gpt-5.2",
                 "openai_api_key": "sly_data"},
            ]
        }
        side_effect: List[Any] = [
            {"anthropic_api_key"},
            {"openai_api_key"},
        ]
        run_context = self._make_run_context(llm_config, side_effect)

        with pytest.raises(ValueError) as excinfo:
            run_context.create_agent_with_fallbacks("dummy instructions")

        message: str = str(excinfo.value)
        assert "No fully-specified LLM found in llm_config or fallbacks." in message
        assert "requires at least one of the following set in sly_data.llm_config:" in message
        assert "anthropic_api_key" in message
        assert "openai_api_key" in message

    def test_mixed_sly_data_and_construction_failures_surface_both(self):
        """
        When one fallback reports missing sly_data keys and another raises a
        ValueError during construction, the final error message should include
        both the required-key section and the construction-errors section.
        """
        llm_config: Dict[str, Any] = {
            "fallbacks": [
                {"class": "anthropic", "model_name": "claude-sonnet-4-6",
                 "anthropic_api_key": "sly_data"},
                {"class": "openai", "model_name": "gpt-5.2"},
            ]
        }
        side_effect: List[Any] = [
            {"anthropic_api_key"},
            ValueError("openai_api_key missing"),
        ]
        run_context = self._make_run_context(llm_config, side_effect)

        with pytest.raises(ValueError) as excinfo:
            run_context.create_agent_with_fallbacks("dummy instructions")

        message: str = str(excinfo.value)
        assert "requires at least one of the following set in sly_data.llm_config:" in message
        assert "anthropic_api_key" in message
        assert "The following errors occurred while constructing LLMs:" in message
        assert "openai_api_key missing" in message

    def test_all_fallbacks_failing_surfaces_collected_errors(self):
        """
        When every fallback raises ValueError during construction, the final
        ValueError should list all collected construction errors under a clear
        section header so the operator can see why each candidate failed.
        """
        llm_config: Dict[str, Any] = {
            "fallbacks": [
                {"class": "anthropic", "model_name": "claude-sonnet-4-6"},
                {"class": "openai", "model_name": "gpt-5.2"},
            ]
        }
        side_effect: List[Any] = [
            ValueError("anthropic_api_key missing"),
            ValueError("openai_api_key missing"),
        ]
        run_context = self._make_run_context(llm_config, side_effect)

        with pytest.raises(ValueError) as excinfo:
            run_context.create_agent_with_fallbacks("dummy instructions")

        message: str = str(excinfo.value)
        assert "No fully-specified LLM found in llm_config or fallbacks." in message
        assert "The following errors occurred while constructing LLMs:" in message
        assert "anthropic_api_key missing" in message
        assert "openai_api_key missing" in message
        # Construction errors should be on their own line, not glued onto the base sentence.
        assert "fallbacks.anthropic_api_key" not in message
