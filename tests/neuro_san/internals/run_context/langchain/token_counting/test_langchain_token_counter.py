
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

from unittest import TestCase
from unittest.mock import Mock

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor
from typing_extensions import override

from neuro_san.internals.run_context.langchain.token_counting.langchain_token_counter import LangChainTokenCounter


class TestLangChainTokenCounter(TestCase):
    """
    Tests for LangChainTokenCounter: sum_all_tokens() and merge_dicts().
    The count_tokens() timeout, report() and nested agent tests are in TestLangChainTokenCounterTimeout,
    TestLangChainTokenCounterReport and TestLangChainTokenCounterNestedAgents.
    """

    @override
    def setUp(self) -> None:
        """
        Gives each test a fresh LangChainTokenCounter built on mocked dependencies.
        """
        # Mock the required dependencies
        mock_llm: Mock = Mock()
        mock_invocation_context: Mock = Mock()
        mock_journal: Mock = Mock()
        mock_origin: Mock = Mock()

        self.token_counter: LangChainTokenCounter = LangChainTokenCounter(
            llm=mock_llm,
            invocation_context=mock_invocation_context,
            journal=mock_journal,
            origin=mock_origin
        )

    def test_sum_all_tokens_single_provider_single_model(self) -> None:
        """
        Test aggregation with a single provider and single model.
        """
        token_dict: Dict[str, Any] = {
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

        token_totals: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 3.0)

        expected: Dict[str, Any] = {
            "total_tokens": 100,
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "successful_requests": 1,
            "empty_responses": 0,
            "total_cost": 0.05,
            "time_taken_in_seconds": 3.0  # Uses the time_value parameter
        }

        self.assertEqual(token_totals, expected)

    def test_sum_all_tokens_single_provider_multiple_models(self) -> None:
        """
        Test aggregation with a single provider and multiple models.
        """
        token_dict: Dict[str, Any] = {
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

        token_totals: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 4.5)

        expected: Dict[str, Any] = {
            "total_tokens": 300,
            "prompt_tokens": 230,
            "completion_tokens": 70,
            "successful_requests": 3,
            "empty_responses": 0,
            "total_cost": 0.08,
            "time_taken_in_seconds": 4.5
        }

        self.assertEqual(token_totals, expected)

    def test_sum_all_tokens_multiple_providers_multiple_models(self) -> None:
        """
        Test aggregation with multiple providers and multiple models.
        """
        token_dict: Dict[str, Any] = {
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

        token_totals: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 7.0)

        expected: Dict[str, Any] = {
            "total_tokens": 450,
            "prompt_tokens": 340,
            "completion_tokens": 110,
            "successful_requests": 4,
            "empty_responses": 0,
            "total_cost": 0.20,
            "time_taken_in_seconds": 7.0
        }

        self.assertEqual(token_totals, expected)

    def test_sum_all_tokens_empty_dict(self) -> None:
        """
        Aggregation of an empty token dictionary yields explicit zeros.
        The standard metric keys must always be present: downstream consumers
        (e.g. TokenAccountingMessageFilter) rely on "total_tokens" existing.
        """
        token_dict: Dict[str, Any] = {}

        token_totals: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 1.5)

        expected: Dict[str, Any] = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "successful_requests": 0,
            "empty_responses": 0,
            "total_cost": 0.0,
            "time_taken_in_seconds": 1.5
        }

        self.assertEqual(token_totals, expected)

    def test_sum_all_tokens_empty_models(self) -> None:
        """
        Test aggregation with empty models in providers yields explicit zeros.
        """
        token_dict: Dict[str, Any] = {
            "openai": {},
            "anthropic": {}
        }

        token_totals: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 2.0)

        expected: Dict[str, Any] = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "successful_requests": 0,
            "empty_responses": 0,
            "total_cost": 0.0,
            "time_taken_in_seconds": 2.0
        }

        self.assertEqual(token_totals, expected)

    def test_sum_all_tokens_excludes_time_from_models(self) -> None:
        """
        Test that time_taken_in_seconds from models is excluded from aggregation.
        """
        token_dict: Dict[str, Any] = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 100,
                    "time_taken_in_seconds": 999.9  # This should be ignored
                }
            }
        }

        token_totals: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 5.0)

        # The time should come from the parameter, not the model stats
        time_taken_in_seconds: float = token_totals.get("time_taken_in_seconds")
        total_tokens: int = token_totals.get("total_tokens")
        self.assertEqual(time_taken_in_seconds, 5.0)
        self.assertEqual(total_tokens, 100)

    def test_sum_all_tokens_with_zero_values(self) -> None:
        """
        Test aggregation with zero values.
        """
        token_dict: Dict[str, Any] = {
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

        token_totals: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 0.1)

        expected: Dict[str, Any] = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "successful_requests": 0,
            "empty_responses": 0,
            "total_cost": 0.0,
            "time_taken_in_seconds": 0.1
        }

        self.assertEqual(token_totals, expected)

    def test_sum_all_tokens_floating_point_precision(self) -> None:
        """
        Test aggregation with floating point numbers.
        """
        token_dict: Dict[str, Any] = {
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

        token_totals: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 3.5)

        total_cost: float = token_totals.get("total_cost")
        cost_error: float = abs(total_cost - 0.3)
        self.assertLess(cost_error, 1e-10)
        time_taken_in_seconds: float = token_totals.get("time_taken_in_seconds")
        self.assertEqual(time_taken_in_seconds, 3.5)

    def test_merge_dicts_no_overlap(self) -> None:
        """
        Test merging dictionaries with no overlapping keys.
        """
        dict_1: Dict[str, Any] = {
            "a": 1,
            "b": 2
        }
        dict_2: Dict[str, Any] = {
            "c": 3,
            "d": 4
        }

        merged_dict: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        expected: Dict[str, Any] = {
            "a": 1,
            "b": 2,
            "c": 3,
            "d": 4
        }
        self.assertEqual(merged_dict, expected)

    def test_merge_dicts_numeric_overlap(self) -> None:
        """
        Test merging dictionaries with overlapping numeric values.
        """
        dict_1: Dict[str, Any] = {
            "a": 1,
            "b": 2,
            "c": 3
        }
        dict_2: Dict[str, Any] = {
            "a": 4,
            "c": 5,
            "d": 6
        }

        merged_dict: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        expected: Dict[str, Any] = {
            "a": 5,
            "b": 2,
            "c": 8,
            "d": 6
        }
        self.assertEqual(merged_dict, expected)

    def test_merge_dicts_nested_dictionaries(self) -> None:
        """
        Test merging dictionaries with nested dictionary values.
        """
        dict_1: Dict[str, Any] = {
            "provider1": {
                "model1": {
                    "tokens": 100,
                    "cost": 0.05
                }
            }
        }
        dict_2: Dict[str, Any] = {
            "provider1": {
                "model1": {
                    "tokens": 50,
                    "requests": 1
                },
                "model2": {
                    "tokens": 200,
                    "cost": 0.10
                }
            }
        }

        merged_dict: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        expected: Dict[str, Any] = {
            "provider1": {
                "model1": {
                    "tokens": 150,
                    "cost": 0.05,
                    "requests": 1
                },
                "model2": {
                    "tokens": 200,
                    "cost": 0.10
                }
            }
        }
        self.assertEqual(merged_dict, expected)

    def test_merge_dicts_deeply_nested(self) -> None:
        """
        Test merging deeply nested dictionaries.
        """
        dict_1: Dict[str, Any] = {
            "level1": {
                "level2": {
                    "level3": {"value": 10}
                }
            }
        }
        dict_2: Dict[str, Any] = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": 5,
                        "other": 20
                    }
                }
            }
        }

        merged_dict: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        expected: Dict[str, Any] = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": 15,
                        "other": 20
                    }
                }
            }
        }
        self.assertEqual(merged_dict, expected)

    def test_merge_dicts_mixed_types(self) -> None:
        """
        Test merging with mixed data types (dict vs numeric).
        """
        dict_1: Dict[str, Any] = {
            "a": {"nested": 1},
            "b": 10
        }
        dict_2: Dict[str, Any] = {
            "a": {
                "nested": 2,
                "other": 3
            },
            "b": 5,
            "c": {"new": 4}
        }

        merged_dict: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        expected: Dict[str, Any] = {
            "a": {
                "nested": 3,
                "other": 3
            },
            "b": 15,
            "c": {"new": 4}
        }
        self.assertEqual(merged_dict, expected)

    def test_merge_dicts_empty_dictionaries(self) -> None:
        """
        Test merging with empty dictionaries.
        """
        dict_1: Dict[str, Any] = {}
        dict_2: Dict[str, Any] = {
            "a": 1,
            "b": 2
        }

        merged_dict: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        expected: Dict[str, Any] = {
            "a": 1,
            "b": 2
        }
        self.assertEqual(merged_dict, expected)

        # Swapped on purpose: with one empty operand, merge_dicts() gives the same result in either order.
        reversed_merged_dict: Dict[str, Any] = self.token_counter.merge_dicts(dict_1=dict_2, dict_2=dict_1)
        self.assertEqual(reversed_merged_dict, expected)

    def test_merge_dicts_both_empty(self) -> None:
        """
        Test merging two empty dictionaries.
        """
        dict_1: Dict[str, Any] = {}
        dict_2: Dict[str, Any] = {}

        merged_dict: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        self.assertEqual(merged_dict, {})

    def test_merge_dicts_does_not_modify_originals(self) -> None:
        """
        Test that merge_dicts does not modify the original dictionaries.
        """
        dict_1: Dict[str, Any] = {
            "a": 1,
            "b": {"nested": 2}
        }
        dict_2: Dict[str, Any] = {
            "a": 3,
            "b": {"nested": 4},
            "c": 5
        }

        dict_1_original: Dict[str, Any] = {
            "a": 1,
            "b": {"nested": 2}
        }
        dict_2_original: Dict[str, Any] = {
            "a": 3,
            "b": {"nested": 4},
            "c": 5
        }

        merged_dict: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        # Original dictionaries should remain unchanged
        self.assertEqual(dict_1, dict_1_original)
        self.assertEqual(dict_2, dict_2_original)

        # Result should be different from originals
        self.assertNotEqual(merged_dict, dict_1)
        self.assertNotEqual(merged_dict, dict_2)

    def test_merge_dicts_complex_token_scenario(self) -> None:
        """
        Test merging with a realistic token counting scenario.
        """
        existing_models: Dict[str, Any] = {
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

        new_models: Dict[str, Any] = {
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

        merged_dict: Dict[str, Any] = self.token_counter.merge_dicts(existing_models, new_models)

        expected: Dict[str, Any] = {
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

        self.assertEqual(merged_dict, expected)

    def test_sum_all_tokens_aggregates_empty_responses(self) -> None:
        """
        empty_responses sums across providers and models into the network-wide dict.
        """
        token_dict: Dict[str, Any] = {
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

        token_totals: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 3.0)

        empty_responses: int = token_totals.get("empty_responses")
        successful_requests: int = token_totals.get("successful_requests")
        self.assertEqual(empty_responses, 3)
        self.assertEqual(successful_requests, 5)

    def test_merge_dicts_empty_responses_backward_compat(self) -> None:
        """
        merge_dicts carries empty_responses when only one operand has that key, so stats without the key still merge.
        """
        # Accumulator with no empty_responses key.
        existing_models: Dict[str, Any] = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 100,
                    "successful_requests": 1,
                    "total_cost": 0.05
                }
            }
        }
        # Per-callback dict that tracks empty_responses.
        new_models: Dict[str, Any] = {
            "openai": {
                "gpt-4": {
                    "total_tokens": 50,
                    "successful_requests": 1,
                    "empty_responses": 2,
                    "total_cost": 0.02
                }
            }
        }

        merged_dict: Dict[str, Any] = self.token_counter.merge_dicts(existing_models, new_models)

        # DictionaryExtractor splits keys on "."; the model name "gpt-4" has none.
        gpt4_stats: Dict[str, Any] = DictionaryExtractor(merged_dict).get("openai.gpt-4")
        empty_responses: int = gpt4_stats.get("empty_responses")
        successful_requests: int = gpt4_stats.get("successful_requests")
        total_tokens: int = gpt4_stats.get("total_tokens")
        self.assertEqual(empty_responses, 2)
        self.assertEqual(successful_requests, 2)
        self.assertEqual(total_tokens, 150)
