
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from unittest.mock import Mock
import pytest

from neuro_san.internals.run_context.langchain.token_counting.langchain_token_counter import LangChainTokenCounter


class TestLangChainTokenCounter:
    """Test cases for sum_all_tokens and merge_dicts methods."""

    @pytest.fixture
    def token_counter(self):
        """Create a LangChainTokenCounter instance for testing."""
        # Mock the required dependencies
        mock_llm = Mock()
        mock_invocation_context = Mock()
        mock_journal = Mock()

        return LangChainTokenCounter(
            llm=mock_llm,
            invocation_context=mock_invocation_context,
            journal=mock_journal
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
