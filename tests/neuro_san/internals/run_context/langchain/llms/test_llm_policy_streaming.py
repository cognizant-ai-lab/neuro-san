
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
Unit tests for LlmPolicy.is_streaming() configuration handling.

Each per-provider LlmPolicy delegates the streaming-or-not decision to
LlmPolicy.is_streaming(), which reads the "streaming" key from the fully
specified llm config dict. These tests verify the contract that
is_streaming() upholds, so the per-provider policies can rely on it.
"""
import pytest

from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy


class TestLlmPolicyStreaming:
    """
    Verifies that LlmPolicy.is_streaming() correctly reads the "streaming"
    key from the llm config, defaulting to False when absent, and coerces
    arbitrary truthy / falsy values to a clean bool.
    """

    def test_defaults_to_false_when_key_absent(self):
        """
        A config without 'streaming' yields False, preserving the
        long-standing non-streaming default neuro-san has shipped with.
        """
        assert not (LlmPolicy.is_streaming({}))

    def test_true_when_key_is_true(self):
        """Explicit True turns streaming on."""
        assert(LlmPolicy.is_streaming({"streaming": True}))

    def test_false_when_key_is_false(self):
        """Explicit False keeps streaming off."""
        assert not (LlmPolicy.is_streaming({"streaming": False}))

    def test_none_resolves_to_false(self):
        """
        A literal None (which HOCON's `null` produces) is treated as
        streaming off, matching the documented default.
        """
        assert not (LlmPolicy.is_streaming({"streaming": None}))

    def test_truthy_non_bool_coerces_to_true(self):
        """
        Non-boolean truthy values resolve to True. Defensive against
        configs that surface 'streaming' as e.g. an int or string.
        """
        assert (LlmPolicy.is_streaming({"streaming": 1}))
        assert (LlmPolicy.is_streaming({"streaming": "yes"}))
        assert not (LlmPolicy.is_streaming({"streaming": ["x"]}))

    def test_falsy_non_bool_coerces_to_false(self):
        """Non-boolean falsy values resolve to False."""
        assert not (LlmPolicy.is_streaming({"streaming": 0}))
        assert not (LlmPolicy.is_streaming({"streaming": ""}))
        assert not (LlmPolicy.is_streaming({"streaming": []}))

    def test_other_config_keys_do_not_affect_result(self):
        """Only the 'streaming' key is consulted; siblings are ignored."""
        assert not (LlmPolicy.is_streaming({"stream_usage": True}))
        assert (LlmPolicy.is_streaming({"streaming": True, "stream_usage": False}))
