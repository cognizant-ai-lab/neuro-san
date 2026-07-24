
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
# pylint: disable=protected-access

import asyncio

import pytest

from neuro_san.internals.run_context.langchain.llms.gemini_llm_policy import GeminiLlmPolicy

try:
    from google.genai.types import AutomaticFunctionCallingConfig
    HAS_GOOGLE_GENAI = True
except ImportError:
    HAS_GOOGLE_GENAI = False


class _ChatModelLikeBinding:
    """Stands in for langchain-core >= 1.4's chat-model-aware bind() result."""

    def __init__(self, bound, kwargs):
        self.bound = bound
        self.kwargs = kwargs

    def bind_tools(self, *args, **kwargs):
        """Presence of this method marks the binding as chat-model-aware."""

    def close(self):
        """Recording close() so this can double as a client stub."""
        self.bound.closed_clients.append("sync")

    async def aclose(self):
        """Recording aclose() so this can double as a client stub."""
        self.bound.closed_clients.append("async")


class _LegacyBinding:
    """Stands in for older langchain-core's generic RunnableBinding (no bind_tools)."""

    def __init__(self, bound, kwargs):
        self.bound = bound
        self.kwargs = kwargs


class _StubChat:
    """Stands in for ChatGoogleGenerativeAI."""

    binding_class = _ChatModelLikeBinding

    def __init__(self):
        self.closed_clients = []
        self.client = _ChatModelLikeBinding(self, {})
        self.async_client = _ChatModelLikeBinding(self, {})

    def bind(self, **kwargs):
        """Mimic Runnable.bind(), recording the kwargs."""
        return self.binding_class(self, kwargs)


class _LegacyStubChat(_StubChat):
    """Stands in for ChatGoogleGenerativeAI on an older langchain-core."""

    binding_class = _LegacyBinding


class TestGeminiLlmPolicyAfcDisabled:
    """
    Test cases for GeminiLlmPolicy._disable_afc().

    Background: the google-genai SDK logs a misleading
    "AFC is enabled with max remote calls: 10." banner unless Automatic
    Function Calling is explicitly disabled per-request.
    See https://github.com/cognizant-ai-lab/neuro-san/issues/1096
    """

    @pytest.mark.skipif(not HAS_GOOGLE_GENAI, reason="google-genai SDK not installed")
    def test_binds_afc_disable(self):
        """On a chat-model-aware langchain-core, the llm is bound with the AFC-disable setting."""
        llm = _StubChat()
        result = GeminiLlmPolicy()._disable_afc(llm)
        assert isinstance(result, _ChatModelLikeBinding)
        assert result.bound is llm
        afc = result.kwargs.get("automatic_function_calling")
        assert isinstance(afc, AutomaticFunctionCallingConfig)
        assert afc.disable is True

    @pytest.mark.skipif(not HAS_GOOGLE_GENAI, reason="google-genai SDK not installed")
    def test_passthrough_on_legacy_langchain_core(self):
        """When bind() yields a binding without bind_tools(), the raw llm is returned unchanged."""
        llm = _LegacyStubChat()
        result = GeminiLlmPolicy()._disable_afc(llm)
        assert result is llm

    @pytest.mark.skipif(HAS_GOOGLE_GENAI, reason="google-genai SDK is installed")
    def test_passthrough_without_google_genai(self):
        """Without the google-genai SDK there is no AFC, so the llm is returned unchanged."""
        llm = _StubChat()
        result = GeminiLlmPolicy()._disable_afc(llm)
        assert result is llm

    def test_delete_resources_unwraps_binding(self):
        """delete_resources() must reach the clients through a bind() wrapper."""
        llm = _StubChat()
        policy = GeminiLlmPolicy()
        policy.llm = llm.bind(automatic_function_calling="anything")

        asyncio.run(policy.delete_resources())

        assert llm.closed_clients == ["sync", "async"]
        assert policy.llm is None

    def test_delete_resources_works_unwrapped(self):
        """delete_resources() must still work when the llm is not wrapped."""
        llm = _StubChat()
        policy = GeminiLlmPolicy()
        policy.llm = llm

        asyncio.run(policy.delete_resources())

        assert llm.closed_clients == ["sync", "async"]
        assert policy.llm is None
