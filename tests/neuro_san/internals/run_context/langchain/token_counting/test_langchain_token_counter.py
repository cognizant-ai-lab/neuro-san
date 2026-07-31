
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
from contextlib import contextmanager
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from langchain_core.messages.ai import AIMessage

from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.run_context.langchain.token_counting.langchain_token_counter import LangChainTokenCounter
from neuro_san.internals.run_context.langchain.token_counting.langchain_token_counter import ORIGIN_INFO


@contextmanager
def origin_scope(origin_str: str):
    """
    Set the ORIGIN_INFO ContextVar the way count_tokens() does before calling report().
    """
    token = ORIGIN_INFO.set(origin_str)
    try:
        yield
    finally:
        ORIGIN_INFO.reset(token)


# pylint: disable=too-many-public-methods
class TestLangChainTokenCounter:
    """Test cases for sum_all_tokens and merge_dicts methods."""

    @pytest.fixture
    def token_counter(self):
        """Create a LangChainTokenCounter instance for testing."""
        # Mock the required dependencies
        mock_llm = Mock()
        mock_invocation_context = Mock()
        mock_journal = Mock()
        mock_origin = Mock()

        return LangChainTokenCounter(
            llm=mock_llm,
            invocation_context=mock_invocation_context,
            journal=mock_journal,
            origin=mock_origin
        )

    def test_sum_all_tokens_single_provider_single_model(self, token_counter):
        """Test aggregation with a single provider and single model."""
        token_dict = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 100,
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                    "successful_requests": 1,
                    "total_cost": 0.05,
                    "time_taken_in_seconds": 2.5
                }
            }
        }

        result = token_counter.sum_all_tokens(token_dict, 3.0)

        expected = {
            "total_tokens": 100,
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "successful_requests": 1,
            "total_cost": 0.05,
            "time_taken_in_seconds": 3.0  # Uses the time_value parameter
        }

        assert result == expected

    def test_sum_all_tokens_single_provider_multiple_models(self, token_counter):
        """Test aggregation with a single provider and multiple models."""
        token_dict = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 100,
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                    "successful_requests": 1,
                    "total_cost": 0.05,
                    "time_taken_in_seconds": 2.5
                },
                "gpt-3.5-turbo": {
                    "total_tokens": 200,
                    "prompt_tokens": 150,
                    "completion_tokens": 50,
                    "successful_requests": 2,
                    "total_cost": 0.03,
                    "time_taken_in_seconds": 1.8
                }
            }
        }

        result = token_counter.sum_all_tokens(token_dict, 4.5)

        expected = {
            "total_tokens": 300,
            "prompt_tokens": 230,
            "completion_tokens": 70,
            "successful_requests": 3,
            "total_cost": 0.08,
            "time_taken_in_seconds": 4.5
        }

        assert result == expected

    def test_sum_all_tokens_multiple_providers_multiple_models(self, token_counter):
        """Test aggregation with multiple providers and multiple models."""
        token_dict = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 100,
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                    "successful_requests": 1,
                    "total_cost": 0.05,
                    "time_taken_in_seconds": 2.5
                }
            },
            "anthropic": {
                "claude-3-sonnet": {
                    "total_tokens": 150,
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "successful_requests": 1,
                    "total_cost": 0.03,
                    "time_taken_in_seconds": 1.2
                },
                "claude-3-opus": {
                    "total_tokens": 200,
                    "prompt_tokens": 160,
                    "completion_tokens": 40,
                    "successful_requests": 2,
                    "total_cost": 0.12,
                    "time_taken_in_seconds": 3.1
                }
            }
        }

        result = token_counter.sum_all_tokens(token_dict, 7.0)

        expected = {
            "total_tokens": 450,
            "prompt_tokens": 340,
            "completion_tokens": 110,
            "successful_requests": 4,
            "total_cost": 0.20,
            "time_taken_in_seconds": 7.0
        }

        assert result == expected

    def test_sum_all_tokens_empty_dict(self, token_counter):
        """Test aggregation with empty token dictionary."""
        token_dict = {}

        result = token_counter.sum_all_tokens(token_dict, 1.5)

        expected = {
            "time_taken_in_seconds": 1.5
        }

        assert result == expected

    def test_sum_all_tokens_empty_models(self, token_counter):
        """Test aggregation with empty models in providers."""
        token_dict = {
            "openai": {},
            "anthropic": {}
        }

        result = token_counter.sum_all_tokens(token_dict, 2.0)

        expected = {
            "time_taken_in_seconds": 2.0
        }

        assert result == expected

    def test_sum_all_tokens_excludes_time_from_models(self, token_counter):
        """Test that time_taken_in_seconds from models is excluded from aggregation."""
        token_dict = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 100,
                    "time_taken_in_seconds": 999.9  # This should be ignored
                }
            }
        }

        result = token_counter.sum_all_tokens(token_dict, 5.0)

        # The time should come from the parameter, not the model stats
        assert result["time_taken_in_seconds"] == 5.0
        assert result["total_tokens"] == 100

    def test_sum_all_tokens_with_zero_values(self, token_counter):
        """Test aggregation with zero values."""
        token_dict = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "successful_requests": 0,
                    "total_cost": 0.0,
                    "time_taken_in_seconds": 0.0
                }
            }
        }

        result = token_counter.sum_all_tokens(token_dict, 0.1)

        expected = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "successful_requests": 0,
            "total_cost": 0.0,
            "time_taken_in_seconds": 0.1
        }

        assert result == expected

    def test_sum_all_tokens_floating_point_precision(self, token_counter):
        """Test aggregation with floating point numbers."""
        token_dict = {
            "openai": {
                "gpt-4": {
                    "total_cost": 0.1,
                    "time_taken_in_seconds": 1.1
                }
            },
            "anthropic": {
                "claude-3": {
                    "total_cost": 0.2,
                    "time_taken_in_seconds": 2.2
                }
            }
        }

        result = token_counter.sum_all_tokens(token_dict, 3.5)

        assert abs(result["total_cost"] - 0.3) < 1e-10
        assert result["time_taken_in_seconds"] == 3.5

    def test_merge_dicts_no_overlap(self, token_counter):
        """Test merging dictionaries with no overlapping keys."""
        dict_1 = {"a": 1, "b": 2}
        dict_2 = {"c": 3, "d": 4}

        result = token_counter.merge_dicts(dict_1, dict_2)

        expected = {"a": 1, "b": 2, "c": 3, "d": 4}
        assert result == expected

    def test_merge_dicts_numeric_overlap(self, token_counter):
        """Test merging dictionaries with overlapping numeric values."""
        dict_1 = {"a": 1, "b": 2, "c": 3}
        dict_2 = {"a": 4, "c": 5, "d": 6}

        result = token_counter.merge_dicts(dict_1, dict_2)

        expected = {"a": 5, "b": 2, "c": 8, "d": 6}
        assert result == expected

    def test_merge_dicts_nested_dictionaries(self, token_counter):
        """Test merging dictionaries with nested dictionary values."""
        dict_1 = {
            "provider1": {
                "model1": {"tokens": 100, "cost": 0.05}
            }
        }
        dict_2 = {
            "provider1": {
                "model1": {"tokens": 50, "requests": 1},
                "model2": {"tokens": 200, "cost": 0.10}
            }
        }

        result = token_counter.merge_dicts(dict_1, dict_2)

        expected = {
            "provider1": {
                "model1": {"tokens": 150, "cost": 0.05, "requests": 1},
                "model2": {"tokens": 200, "cost": 0.10}
            }
        }
        assert result == expected

    def test_merge_dicts_deeply_nested(self, token_counter):
        """Test merging deeply nested dictionaries."""
        dict_1 = {
            "level1": {
                "level2": {
                    "level3": {"value": 10}
                }
            }
        }
        dict_2 = {
            "level1": {
                "level2": {
                    "level3": {"value": 5, "other": 20}
                }
            }
        }

        result = token_counter.merge_dicts(dict_1, dict_2)

        expected = {
            "level1": {
                "level2": {
                    "level3": {"value": 15, "other": 20}
                }
            }
        }
        assert result == expected

    def test_merge_dicts_mixed_types(self, token_counter):
        """Test merging with mixed data types (dict vs numeric)."""
        dict_1 = {
            "a": {"nested": 1},
            "b": 10
        }
        dict_2 = {
            "a": {"nested": 2, "other": 3},
            "b": 5,
            "c": {"new": 4}
        }

        result = token_counter.merge_dicts(dict_1, dict_2)

        expected = {
            "a": {"nested": 3, "other": 3},
            "b": 15,
            "c": {"new": 4}
        }
        assert result == expected

    def test_merge_dicts_empty_dictionaries(self, token_counter):
        """Test merging with empty dictionaries."""
        dict_1 = {}
        dict_2 = {"a": 1, "b": 2}

        result = token_counter.merge_dicts(dict_1, dict_2)

        expected = {"a": 1, "b": 2}
        assert result == expected

        # Test the reverse
        result2 = token_counter.merge_dicts(dict_2, dict_1)
        assert result2 == {"a": 1, "b": 2}

    def test_merge_dicts_both_empty(self, token_counter):
        """Test merging two empty dictionaries."""
        dict_1 = {}
        dict_2 = {}

        result = token_counter.merge_dicts(dict_1, dict_2)

        assert result == {}

    def test_merge_dicts_does_not_modify_originals(self, token_counter):
        """Test that merge_dicts does not modify the original dictionaries."""
        dict_1 = {"a": 1, "b": {"nested": 2}}
        dict_2 = {"a": 3, "b": {"nested": 4}, "c": 5}

        dict_1_original = {"a": 1, "b": {"nested": 2}}
        dict_2_original = {"a": 3, "b": {"nested": 4}, "c": 5}

        result = token_counter.merge_dicts(dict_1, dict_2)

        # Original dictionaries should remain unchanged
        assert dict_1 == dict_1_original
        assert dict_2 == dict_2_original

        # Result should be different from originals
        assert result != dict_1
        assert result != dict_2

    @pytest.mark.asyncio
    async def test_count_tokens_timeout_writes_aimessage_before_token_accounting_and_raises(self):
        """
        On AsyncTimeout, count_tokens should:
        1. Write a final AIMessage to the journal BEFORE report() writes its
           token-accounting AgentMessages, so the journal stream order matches
           the normal-completion path.
        2. Re-raise AsyncTimeout so the caller (RunContextRunnable.run_it) can
           log/handle it.
        """
        # Capture journal.write_message arguments in call order.
        written_messages = []

        async def record(msg, *_args, **_kwargs):
            written_messages.append(msg)

        mock_journal = MagicMock()
        mock_journal.write_message = AsyncMock(side_effect=record)

        # Mock the invocation_context dependencies that count_tokens / report touch.
        mock_invocation_context = MagicMock()
        mock_invocation_context.get_llm_factory.return_value.llm_infos = {}
        mock_invocation_context.get_request_reporting.return_value = {}
        # Not a clone: report() writes the network token message for front men.
        mock_invocation_context.is_cloned.return_value = False

        # The executor wraps the awaitable in a real asyncio.Task so
        # asyncio.wait_for() actually times out and cancels it.
        mock_executor = MagicMock()
        mock_executor.create_task.side_effect = (
            lambda awaitable, _origin_str: asyncio.create_task(awaitable)
        )
        mock_invocation_context.get_asyncio_executor.return_value = mock_executor

        counter = LangChainTokenCounter(
            llm=MagicMock(),
            invocation_context=mock_invocation_context,
            journal=mock_journal,
            # Single-element origin -> no "." in the full name, so report()
            # exercises both the per-agent and network token-message branches.
            origin=[{"tool": "test_agent", "instantiation_index": 0}],
        )

        async def slow_awaitable():
            await asyncio.sleep(10)

        @contextmanager
        def fake_callback_cm(_llm_infos):
            cb = MagicMock()
            cb.models_token_dict = {}
            cb.total_tokens = 0
            cb.prompt_tokens = 0
            cb.completion_tokens = 0
            cb.successful_requests = 0
            cb.empty_responses = 0
            cb.total_cost = 0.0
            yield cb

        callback_path = (
            "neuro_san.internals.run_context.langchain.token_counting."
            "langchain_token_counter.get_llm_token_callback"
        )

        with patch(callback_path, fake_callback_cm):
            with pytest.raises(asyncio.TimeoutError):
                await counter.count_tokens(slow_awaitable(), max_execution_seconds=0.05)

        # 1) First journal write must be the synthesized timeout AIMessage.
        assert written_messages, "Expected at least the timeout AIMessage on the journal"
        first = written_messages[0]
        assert isinstance(first, AIMessage), (
            f"First journal message should be AIMessage, got {type(first).__name__}"
        )
        assert "max_execution_seconds" in first.content

        # 2) Any subsequent messages should be token-accounting AgentMessages
        #    (report() writes per-agent and, for the frontman, network token messages).
        assert len(written_messages) >= 2, (
            "Expected token-accounting AgentMessage(s) after the timeout AIMessage"
        )
        for msg in written_messages[1:]:
            assert isinstance(msg, AgentMessage), (
                f"Expected AgentMessage after AIMessage, got {type(msg).__name__}"
            )

    def test_merge_dicts_complex_token_scenario(self, token_counter):
        """Test merging with a realistic token counting scenario."""
        existing_models = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 100,
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                    "successful_requests": 1,
                    "total_cost": 0.05
                }
            }
        }

        new_models = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 150,
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "successful_requests": 1,
                    "total_cost": 0.075
                },
                "gpt-3.5-turbo": {
                    "total_tokens": 200,
                    "prompt_tokens": 160,
                    "completion_tokens": 40,
                    "successful_requests": 2,
                    "total_cost": 0.02
                }
            },
            "anthropic": {
                "claude-3": {
                    "total_tokens": 300,
                    "prompt_tokens": 250,
                    "completion_tokens": 50,
                    "successful_requests": 1,
                    "total_cost": 0.15
                }
            }
        }

        result = token_counter.merge_dicts(existing_models, new_models)

        expected = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 250,
                    "prompt_tokens": 200,
                    "completion_tokens": 50,
                    "successful_requests": 2,
                    "total_cost": 0.125
                },
                "gpt-3.5-turbo": {
                    "total_tokens": 200,
                    "prompt_tokens": 160,
                    "completion_tokens": 40,
                    "successful_requests": 2,
                    "total_cost": 0.02
                }
            },
            "anthropic": {
                "claude-3": {
                    "total_tokens": 300,
                    "prompt_tokens": 250,
                    "completion_tokens": 50,
                    "successful_requests": 1,
                    "total_cost": 0.15
                }
            }
        }

        assert result == expected

    def test_sum_all_tokens_aggregates_empty_responses(self, token_counter):
        """empty_responses sums across providers and models into the network-wide dict."""
        token_dict = {
            "ollama": {
                "gpt-oss:20B": {
                    "total_tokens": 10,
                    "prompt_tokens": 10,
                    "completion_tokens": 0,
                    "successful_requests": 2,
                    "empty_responses": 1,
                    "total_cost": 0.0,
                    "time_taken_in_seconds": 1.0
                }
            },
            "openai": {
                "gpt-4": {
                    "total_tokens": 100,
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                    "successful_requests": 3,
                    "empty_responses": 2,
                    "total_cost": 0.05,
                    "time_taken_in_seconds": 2.5
                }
            }
        }

        result = token_counter.sum_all_tokens(token_dict, 3.0)

        assert result["empty_responses"] == 3
        assert result["successful_requests"] == 5

    def test_merge_dicts_empty_responses_backward_compat(self, token_counter):
        """merge_dicts carries empty_responses even when one operand predates the key."""
        # Older serialized accumulator written before empty_responses existed.
        existing = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 100,
                    "successful_requests": 1,
                    "total_cost": 0.05
                }
            }
        }
        # Newer per-callback dict that tracks empty_responses.
        new = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 50,
                    "successful_requests": 1,
                    "empty_responses": 2,
                    "total_cost": 0.02
                }
            }
        }

        result = token_counter.merge_dicts(existing, new)

        gpt4 = result["openai"]["gpt-4"]
        assert gpt4["empty_responses"] == 2
        assert gpt4["successful_requests"] == 2
        assert gpt4["total_tokens"] == 150


class TestReport:
    """
    Test cases for report(): request-level accumulation and network-message gating.

    Each agent's report() merges its callback's models_token_dict (that agent's own
    LLM calls only) into the shared request_reporting, so request-level totals must
    count every LLM call exactly once regardless of agent nesting.  The request-level
    network message must only be written by the top-level front man: dot-less origin
    and a non-cloned InvocationContext.
    """

    def _make_counter(self, request_reporting, cloned, journal):
        """Build a LangChainTokenCounter around a shared request_reporting dict."""
        mock_invocation_context = MagicMock()
        mock_invocation_context.get_request_reporting.return_value = request_reporting
        mock_invocation_context.is_cloned.return_value = cloned
        return LangChainTokenCounter(
            llm=MagicMock(),
            invocation_context=mock_invocation_context,
            journal=journal,
            origin=[{"tool": "test_agent", "instantiation_index": 0}],
        )

    def _make_callback(self, own_tokens, own_requests, subtree_tokens=None, subtree_requests=None):
        """
        Build a callback stand-in mirroring LlmTokenCallbackHandler semantics:
        models_token_dict covers only the agent's own calls, while the scalar
        totals cover the agent's whole subtree.
        """
        callback = MagicMock()
        callback.models_token_dict = {
            "openai": {
                "gpt-4": {
                    "total_tokens": own_tokens,
                    "prompt_tokens": own_tokens,
                    "completion_tokens": 0,
                    "successful_requests": own_requests,
                    "empty_responses": 0,
                    "total_cost": 0.0,
                    "time_taken_in_seconds": 1.0
                }
            }
        }
        callback.total_tokens = subtree_tokens if subtree_tokens is not None else own_tokens
        callback.prompt_tokens = callback.total_tokens
        callback.completion_tokens = 0
        callback.successful_requests = subtree_requests if subtree_requests is not None else own_requests
        callback.empty_responses = 0
        callback.total_cost = 0.0
        return callback

    @pytest.mark.asyncio
    async def test_report_counts_each_agents_own_calls_exactly_once(self):
        """
        Nested completions must not double count: even though the front man's
        subtree scalars include the downstream agent's tokens, only each agent's
        own (exclusive) per-model stats are merged into request_reporting.
        """
        request_reporting = {}

        # A downstream agent finishes first: 15 tokens / 1 call of its own.
        downstream = self._make_counter(request_reporting, cloned=False, journal=None)
        with origin_scope("front_man.downstream"):
            await downstream.report(self._make_callback(own_tokens=15, own_requests=1), 1.0)

        # The front man finishes last: 30 tokens / 2 calls of its own,
        # 45 tokens / 3 calls across its subtree.
        front_man = self._make_counter(request_reporting, cloned=False, journal=None)
        with origin_scope("front_man"):
            await front_man.report(
                self._make_callback(own_tokens=30, own_requests=2, subtree_tokens=45, subtree_requests=3),
                2.0)

        # Request-level totals equal the sum of each agent's own calls: no double count.
        total_accounting = request_reporting["total_token_accounting"]
        assert total_accounting["total_tokens"] == 45
        assert total_accounting["successful_requests"] == 3
        assert total_accounting["models"]["openai"]["gpt-4"]["total_tokens"] == 45
        assert total_accounting["models"]["openai"]["gpt-4"]["successful_requests"] == 3
        # The last reporter (the front man) stamps the request latency.
        assert total_accounting["time_taken_in_seconds"] == 2.0
        # With no external agents in play, the main network accounting matches the totals.
        main_accounting = request_reporting["token_accounting"]
        assert main_accounting["total_tokens"] == 45
        assert main_accounting["successful_requests"] == 3

    @pytest.mark.asyncio
    async def test_report_separates_main_network_from_total(self):
        """
        Agents of same-server external networks (cloned InvocationContexts)
        contribute to the request totals but not to the "main_network" breakdown.
        """
        request_reporting = {}

        # An external network's front man finishes first: 15 tokens / 1 call.
        external = self._make_counter(request_reporting, cloned=True, journal=None)
        with origin_scope("external_front_man"):
            await external.report(self._make_callback(own_tokens=15, own_requests=1), 1.0)

        # The main network's front man finishes last: 30 tokens / 2 calls of its own.
        front_man = self._make_counter(request_reporting, cloned=False, journal=None)
        with origin_scope("front_man"):
            await front_man.report(
                self._make_callback(own_tokens=30, own_requests=2, subtree_tokens=45, subtree_requests=3),
                2.0)

        # Totals cover main network + same-server external agents, exactly once each.
        total_accounting = request_reporting["total_token_accounting"]
        assert total_accounting["total_tokens"] == 45
        assert total_accounting["successful_requests"] == 3
        # "token_accounting" keeps its historically-documented meaning: the main
        # network only, excluding external agents (and no per-model breakdown).
        main_accounting = request_reporting["token_accounting"]
        assert main_accounting["total_tokens"] == 30
        assert main_accounting["successful_requests"] == 2
        assert "models" not in main_accounting
        # The server log prints the main network accounting first and the request
        # total last, even though an external agent reported first here.
        assert list(request_reporting.keys()) == \
            ["token_accounting", "total_token_accounting"]

    @pytest.mark.asyncio
    async def test_report_network_message_gating(self):
        """
        Only the front man of the main network (dot-less origin, non-cloned
        InvocationContext) writes the two complementary accounting messages:
        main network first, request total second.  Every other agent writes its
        per-agent subtree message, and everyone merges into request_reporting.
        """
        cases = [
            # (origin string, cloned, expected journal writes)
            ("front_man.internal_agent", False, 1),   # internal agent: agent message only
            ("external_front_man", True, 1),          # direct-session external front man: agent message only
            ("front_man", False, 2),                  # main front man: main-network + total messages
        ]
        for origin_str, cloned, expected_writes in cases:
            request_reporting = {}
            journal = MagicMock()
            journal.write_message = AsyncMock()

            counter = self._make_counter(request_reporting, cloned=cloned, journal=journal)
            with origin_scope(origin_str):
                await counter.report(self._make_callback(own_tokens=10, own_requests=1), 1.0)

            assert journal.write_message.call_count == expected_writes, \
                f"origin={origin_str} cloned={cloned}"
            # The merge into request_reporting happens for everyone.
            assert request_reporting["total_token_accounting"]["total_tokens"] == 10

        # For the main front man (last case), the two messages are exactly the two
        # accounting entries of request_reporting, so the client-visible accounting
        # and the server log read the same.

        # The first message covers the main network only - no models breakdown,
        # same shape as the per-agent messages.
        main_message = journal.write_message.call_args_list[0].args[0]
        assert isinstance(main_message, AgentMessage)
        assert main_message.structure == request_reporting["token_accounting"]
        assert main_message.structure.get("total_tokens") == 10
        assert "models" not in main_message.structure
        assert "main agent network only" in main_message.structure["caveats"][0]

        # The second message is the request total with the per-model breakdown.
        total_message = journal.write_message.call_args_list[1].args[0]
        assert isinstance(total_message, AgentMessage)
        assert total_message.structure == request_reporting["total_token_accounting"]
        assert total_message.structure.get("total_tokens") == 10
        assert total_message.structure.get("models") is not None
        assert "Request total" in total_message.structure["caveats"][0]
