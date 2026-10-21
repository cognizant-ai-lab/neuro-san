
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
from asyncio import Task
from contextlib import contextmanager
from functools import partial

from typing import Any
from typing import Awaitable
from typing import Dict
from typing import Generator
from typing import List

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor
from typing_extensions import override

from neuro_san.internals.run_context.langchain.token_counting.langchain_token_counter import LangChainTokenCounter
from neuro_san.message.types.agent_message import AgentMessage


CALLBACK_PATH: str = (
    "neuro_san.internals.run_context.langchain.token_counting.langchain_token_counter.get_llm_token_callback"
)


# pylint: disable=too-many-public-methods
class TestLangChainTokenCounter(IsolatedAsyncioTestCase):
    """
    Tests for LangChainTokenCounter: sum_all_tokens(), merge_dicts() and the count_tokens() timeout path.
    """

    @override
    def setUp(self) -> None:
        """
        Gives each test a fresh LangChainTokenCounter built on mocked dependencies.
        """
        mock_llm = Mock()
        mock_invocation_context = Mock()
        mock_journal = Mock()
        mock_origin = Mock()

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

        result: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 3.0)

        expected: Dict[str, Any] = {
            "total_tokens": 100,
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "successful_requests": 1,
            "empty_responses": 0,
            "total_cost": 0.05,
            "time_taken_in_seconds": 3.0  # Uses the time_value parameter
        }

        self.assertEqual(result, expected)

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

        result: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 4.5)

        expected: Dict[str, Any] = {
            "total_tokens": 300,
            "prompt_tokens": 230,
            "completion_tokens": 70,
            "successful_requests": 3,
            "empty_responses": 0,
            "total_cost": 0.08,
            "time_taken_in_seconds": 4.5
        }

        self.assertEqual(result, expected)

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

        result: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 7.0)

        expected: Dict[str, Any] = {
            "total_tokens": 450,
            "prompt_tokens": 340,
            "completion_tokens": 110,
            "successful_requests": 4,
            "empty_responses": 0,
            "total_cost": 0.20,
            "time_taken_in_seconds": 7.0
        }

        self.assertEqual(result, expected)

    def test_sum_all_tokens_empty_dict(self) -> None:
        """
        Aggregation of an empty token dictionary yields explicit zeros.
        The standard metric keys must always be present: downstream consumers
        (e.g. TokenAccountingMessageFilter) rely on "total_tokens" existing.
        """
        token_dict: Dict[str, Any] = {}

        result: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 1.5)

        expected: Dict[str, Any] = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "successful_requests": 0,
            "empty_responses": 0,
            "total_cost": 0.0,
            "time_taken_in_seconds": 1.5
        }

        self.assertEqual(result, expected)

    def test_sum_all_tokens_empty_models(self) -> None:
        """
        Test aggregation with empty models in providers yields explicit zeros.
        """
        token_dict: Dict[str, Any] = {
            "openai": {},
            "anthropic": {}
        }

        result: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 2.0)

        expected: Dict[str, Any] = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "successful_requests": 0,
            "empty_responses": 0,
            "total_cost": 0.0,
            "time_taken_in_seconds": 2.0
        }

        self.assertEqual(result, expected)

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

        result: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 5.0)

        # The time should come from the parameter, not the model stats
        self.assertEqual(result.get("time_taken_in_seconds"), 5.0)
        self.assertEqual(result.get("total_tokens"), 100)

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

        result: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 0.1)

        expected: Dict[str, Any] = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "successful_requests": 0,
            "empty_responses": 0,
            "total_cost": 0.0,
            "time_taken_in_seconds": 0.1
        }

        self.assertEqual(result, expected)

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

        result: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 3.5)

        total_cost: float = result.get("total_cost")
        cost_error: float = abs(total_cost - 0.3)
        self.assertLess(cost_error, 1e-10)
        self.assertEqual(result.get("time_taken_in_seconds"), 3.5)

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

        result: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        expected: Dict[str, Any] = {
            "a": 1,
            "b": 2,
            "c": 3,
            "d": 4
        }
        self.assertEqual(result, expected)

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

        result: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        expected: Dict[str, Any] = {
            "a": 5,
            "b": 2,
            "c": 8,
            "d": 6
        }
        self.assertEqual(result, expected)

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

        result: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

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
        self.assertEqual(result, expected)

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

        result: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

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
        self.assertEqual(result, expected)

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

        result: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        expected: Dict[str, Any] = {
            "a": {
                "nested": 3,
                "other": 3
            },
            "b": 15,
            "c": {"new": 4}
        }
        self.assertEqual(result, expected)

    def test_merge_dicts_empty_dictionaries(self) -> None:
        """
        Test merging with empty dictionaries.
        """
        dict_1: Dict[str, Any] = {}
        dict_2: Dict[str, Any] = {
            "a": 1,
            "b": 2
        }

        result: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        expected: Dict[str, Any] = {
            "a": 1,
            "b": 2
        }
        self.assertEqual(result, expected)

        # Swapped on purpose: merge_dicts() gives the same result in either order.
        reversed_result: Dict[str, Any] = self.token_counter.merge_dicts(dict_1=dict_2, dict_2=dict_1)
        self.assertEqual(reversed_result, expected)

    def test_merge_dicts_both_empty(self) -> None:
        """
        Test merging two empty dictionaries.
        """
        dict_1: Dict[str, Any] = {}
        dict_2: Dict[str, Any] = {}

        result: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        self.assertEqual(result, {})

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

        result: Dict[str, Any] = self.token_counter.merge_dicts(dict_1, dict_2)

        # Original dictionaries should remain unchanged
        self.assertEqual(dict_1, dict_1_original)
        self.assertEqual(dict_2, dict_2_original)

        # Result should be different from originals
        self.assertNotEqual(result, dict_1)
        self.assertNotEqual(result, dict_2)

    async def test_count_tokens_timeout_writes_aimessage_before_token_accounting_and_raises(self) -> None:
        """
        On AsyncTimeout, count_tokens should:
        1. Write a final AIMessage to the journal BEFORE report() writes its
           token-accounting AgentMessages, so the journal stream order matches
           the normal-completion path.
        2. Re-raise AsyncTimeout so the caller (RunContextRunnable.run_it) can
           log/handle it.
        """
        # Capture journal.write_message arguments in call order.
        written_messages: List[BaseMessage] = []
        # Single-element origin on a non-cloned context -> report() takes the
        # main-front-man branch and writes the two request-level messages.
        origin: List[Dict[str, Any]] = [
            {
                "tool": "test_agent",
                "instantiation_index": 0
            }
        ]
        counter: LangChainTokenCounter = TestLangChainTokenCounter._make_timeout_counter(origin, written_messages)

        slow_awaitable: Awaitable = TestLangChainTokenCounter._slow_awaitable()

        with patch(CALLBACK_PATH, TestLangChainTokenCounter._fake_token_callback):
            with self.assertRaises(asyncio.TimeoutError):
                await counter.count_tokens(slow_awaitable, max_execution_seconds=0.05)

        # 1) First journal write must be the synthesized timeout AIMessage.
        self.assertTrue(written_messages, "Expected at least the timeout AIMessage on the journal")
        first_message: BaseMessage = written_messages[0]
        self.assertIsInstance(first_message, AIMessage, "First journal message should be AIMessage")
        self.assertIn("max_execution_seconds", first_message.content)

        # 2) The subsequent messages are the front man's two token-accounting
        #    AgentMessages (main network, then request total).
        self.assertEqual(len(written_messages), 3,
                         "Expected the two request-level AgentMessages after the timeout AIMessage")
        message: BaseMessage
        # Every message after the timeout AIMessage is a token-accounting AgentMessage.
        for message in written_messages[1:]:
            self.assertIsInstance(message, AgentMessage, "Expected AgentMessage after AIMessage")

    async def test_count_tokens_timeout_agent_branch_writes_per_agent_message(self) -> None:
        """
        A timed-out non-front-man agent (multi-element origin) still writes its
        per-agent token accounting message after the synthesized AIMessage.
        """
        written_messages: List[BaseMessage] = []
        # Multi-element origin -> report() takes the per-agent else-branch.
        origin: List[Dict[str, Any]] = [
            {
                "tool": "front_man",
                "instantiation_index": 0
            },
            {
                "tool": "slow_agent",
                "instantiation_index": 0
            },
        ]
        counter: LangChainTokenCounter = TestLangChainTokenCounter._make_timeout_counter(origin, written_messages)

        slow_awaitable: Awaitable = TestLangChainTokenCounter._slow_awaitable()

        with patch(CALLBACK_PATH, TestLangChainTokenCounter._fake_token_callback):
            with self.assertRaises(asyncio.TimeoutError):
                await counter.count_tokens(slow_awaitable, max_execution_seconds=0.05)

        # Timeout AIMessage first, then exactly one per-agent AgentMessage.
        self.assertEqual(len(written_messages), 2)
        self.assertIsInstance(written_messages[0], AIMessage)
        agent_message: BaseMessage = written_messages[1]
        self.assertIsInstance(agent_message, AgentMessage)
        caveats: List[str] = agent_message.structure.get("caveats")
        self.assertIn("tracked at the agent level", caveats[0])

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

        result: Dict[str, Any] = self.token_counter.merge_dicts(existing_models, new_models)

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

        self.assertEqual(result, expected)

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

        result: Dict[str, Any] = self.token_counter.sum_all_tokens(token_dict, 3.0)

        self.assertEqual(result.get("empty_responses"), 3)
        self.assertEqual(result.get("successful_requests"), 5)

    def test_merge_dicts_empty_responses_backward_compat(self) -> None:
        """
        merge_dicts carries empty_responses even when one operand has no empty_responses key.
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

        result: Dict[str, Any] = self.token_counter.merge_dicts(existing_models, new_models)

        gpt4: Dict[str, Any] = DictionaryExtractor(result).get("openai.gpt-4")
        self.assertEqual(gpt4.get("empty_responses"), 2)
        self.assertEqual(gpt4.get("successful_requests"), 2)
        self.assertEqual(gpt4.get("total_tokens"), 150)

    @staticmethod
    def _make_timeout_counter(origin: List[Dict[str, Any]],
                              written_messages: List[BaseMessage]) -> LangChainTokenCounter:
        """
        Build a LangChainTokenCounter whose journal records every message and whose
        executor runs a real asyncio.Task, so count_tokens() really times out.

        :param origin: The origin the counter applies to all messages
        :param written_messages: The list that collects every journaled message, in order
        :return: The LangChainTokenCounter under test
        """
        mock_journal = MagicMock()
        record_message: partial = partial(TestLangChainTokenCounter._record, written_messages)
        mock_journal.write_message = AsyncMock(side_effect=record_message)

        # Mock the invocation_context dependencies that count_tokens / report touch.
        mock_invocation_context = MagicMock()
        mock_invocation_context.get_llm_factory.return_value.llm_infos = {}
        mock_invocation_context.get_request_reporting.return_value = {}
        # Not a clone: report() writes the network token message for front men.
        mock_invocation_context.is_cloned.return_value = False

        # The executor wraps the awaitable in a real asyncio.Task so
        # asyncio.wait_for() actually times out and cancels it.
        mock_executor = MagicMock()
        mock_executor.create_task.side_effect = TestLangChainTokenCounter._create_real_task
        mock_invocation_context.get_asyncio_executor.return_value = mock_executor

        counter = LangChainTokenCounter(
            llm=MagicMock(),
            invocation_context=mock_invocation_context,
            journal=mock_journal,
            origin=origin,
        )
        return counter

    @staticmethod
    def _record(written_messages: List[BaseMessage], message: BaseMessage, *_args: Any, **_kwargs: Any) -> None:
        """
        Append the given message to the written list, standing in for Journal.write_message
        so tests can inspect everything the counter journaled.

        :param written_messages: The list that collects every journaled message, in order
        :param message: The message being journaled
        :param _args: Further positional arguments write_message accepts (its origin); ignored
        :param _kwargs: Further keyword arguments write_message accepts; ignored
        """
        written_messages.append(message)

    @staticmethod
    def _create_real_task(awaitable: Awaitable, _submitter_id: str, _raise_exception: bool = False) -> Task:
        """
        Stand in for TaskExecutor.create_task() by wrapping the awaitable in a real asyncio.Task.

        :param awaitable: The awaitable to run
        :param _submitter_id: The submitter id create_task() accepts; ignored
        :param _raise_exception: The raise_exception flag create_task() accepts; ignored
        :return: The running asyncio.Task
        """
        task: Task = asyncio.create_task(awaitable)
        return task

    @staticmethod
    async def _slow_awaitable() -> None:
        """
        Sleep long enough that every count_tokens() timeout in these tests fires first.
        """
        await asyncio.sleep(10)

    @staticmethod
    @contextmanager
    def _fake_token_callback(_llm_infos: Dict[str, Any]) -> Generator[MagicMock, None, None]:
        """
        Stand in for get_llm_token_callback() with a callback that holds zero token counts.

        :param _llm_infos: The llm_infos get_llm_token_callback() accepts; ignored
        :return: A generator that yields the zero-count callback once
        """
        zero_count_callback = MagicMock()
        zero_count_callback.models_token_dict = {}
        zero_count_callback.total_tokens = 0
        zero_count_callback.prompt_tokens = 0
        zero_count_callback.completion_tokens = 0
        zero_count_callback.successful_requests = 0
        zero_count_callback.empty_responses = 0
        zero_count_callback.total_cost = 0.0
        yield zero_count_callback
