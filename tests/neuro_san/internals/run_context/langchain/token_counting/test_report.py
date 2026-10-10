
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
from typing import Optional
from typing import Tuple

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.run_context.langchain.token_counting.langchain_token_counter import LangChainTokenCounter
from neuro_san.message.types.agent_message import AgentMessage


class TestReport(IsolatedAsyncioTestCase):
    """
    Test cases for report(): request-level accumulation and network-message gating.

    Each agent's report() merges its callback's models_token_dict (that agent's own
    LLM calls only) into the shared request_reporting, so request-level totals must
    count every LLM call exactly once regardless of agent nesting.  The request-level
    messages must only be written by the front man of the main network: a
    single-element origin and a non-cloned InvocationContext.
    """

    FRONT_MAN_ORIGIN: List[Dict[str, Any]] = [{"tool": "front_man", "instantiation_index": 0}]
    INTERNAL_AGENT_ORIGIN: List[Dict[str, Any]] = [
        {"tool": "front_man", "instantiation_index": 0},
        {"tool": "internal_agent", "instantiation_index": 0},
    ]
    EXTERNAL_FRONT_MAN_ORIGIN: List[Dict[str, Any]] = [{"tool": "external_front_man", "instantiation_index": 0}]

    async def test_report_counts_each_agents_own_calls_exactly_once(self) -> None:
        """
        Nested completions must not double count: even though the front man's
        subtree scalars include the downstream agent's tokens, only each agent's
        own (exclusive) per-model stats are merged into request_reporting.
        """
        request_reporting: Dict[str, Any] = {}

        # A downstream agent finishes first: 15 tokens / 1 call of its own.
        downstream: LangChainTokenCounter = self._make_counter(request_reporting, cloned=False, journal=None,
                                                               origin=self.INTERNAL_AGENT_ORIGIN)
        downstream_callback: MagicMock = self._make_callback(own_tokens=15, own_requests=1)
        await downstream.report(downstream_callback, 1.0)

        # The front man finishes last: 30 tokens / 2 calls of its own,
        # 45 tokens / 3 calls across its subtree.
        front_man: LangChainTokenCounter = self._make_counter(request_reporting, cloned=False, journal=None)
        front_man_callback: MagicMock = self._make_callback(own_tokens=30, own_requests=2, subtree_tokens=45,
                                                            subtree_requests=3)
        await front_man.report(front_man_callback, 2.0)

        # Request-level totals equal the sum of each agent's own calls: no double count.
        total_accounting: Dict[str, Any] = request_reporting.get("total_token_accounting")
        # DictionaryExtractor splits keys on ".", so these lookups only work for model names without a dot.
        total_accounting_extractor = DictionaryExtractor(total_accounting)
        self.assertEqual(total_accounting.get("total_tokens"), 45)
        self.assertEqual(total_accounting.get("successful_requests"), 3)
        self.assertEqual(total_accounting_extractor.get("models.openai.gpt-4.total_tokens"), 45)
        self.assertEqual(total_accounting_extractor.get("models.openai.gpt-4.successful_requests"), 3)
        # The last reporter (the front man) stamps the request latency.
        self.assertEqual(total_accounting.get("time_taken_in_seconds"), 2.0)
        # With no external agents in play, the main network accounting matches the totals.
        main_accounting: Dict[str, Any] = request_reporting.get("token_accounting")
        self.assertEqual(main_accounting.get("total_tokens"), 45)
        self.assertEqual(main_accounting.get("successful_requests"), 3)

    async def test_report_separates_main_network_from_total(self) -> None:
        """
        Agents of same-server external networks (cloned InvocationContexts)
        contribute to the request totals but not to the main-network "token_accounting".
        """
        request_reporting: Dict[str, Any] = {}

        # An external network's front man finishes first: 15 tokens / 1 call.
        external: LangChainTokenCounter = self._make_counter(request_reporting, cloned=True, journal=None,
                                                             origin=self.EXTERNAL_FRONT_MAN_ORIGIN)
        external_callback: MagicMock = self._make_callback(own_tokens=15, own_requests=1)
        await external.report(external_callback, 1.0)

        # Before any main-network agent reports, the main accounting is an
        # explicit zero entry (not an empty dict), so a request that dies here
        # still logs well-formed accounting.
        early_main_accounting: Dict[str, Any] = request_reporting.get("token_accounting")
        self.assertEqual(early_main_accounting.get("total_tokens"), 0)
        self.assertIn("caveats", early_main_accounting.keys())

        # The main network's front man finishes last: 30 tokens / 2 calls of its own.
        front_man: LangChainTokenCounter = self._make_counter(request_reporting, cloned=False, journal=None)
        front_man_callback: MagicMock = self._make_callback(own_tokens=30, own_requests=2, subtree_tokens=45,
                                                            subtree_requests=3)
        await front_man.report(front_man_callback, 2.0)

        # Totals cover main network + same-server external agents, exactly once each.
        total_accounting: Dict[str, Any] = request_reporting.get("total_token_accounting")
        self.assertEqual(total_accounting.get("total_tokens"), 45)
        self.assertEqual(total_accounting.get("successful_requests"), 3)
        # "token_accounting" keeps its documented meaning: the main
        # network only, excluding external agents (and no per-model breakdown).
        main_accounting: Dict[str, Any] = request_reporting.get("token_accounting")
        self.assertEqual(main_accounting.get("total_tokens"), 30)
        self.assertEqual(main_accounting.get("successful_requests"), 2)
        self.assertNotIn("models", main_accounting.keys())
        # The server log prints the main network accounting first and the request
        # total last, even though an external agent reported first here.
        self.assertEqual(list(request_reporting.keys()), ["token_accounting", "total_token_accounting"])

    async def test_report_late_external_does_not_restamp_request_latency(self) -> None:
        """
        A cloned (external) agent completing after the front man - e.g. an
        "event" invocation that outlives the request - must not replace the
        request latency the front man stamped on the total.
        """
        request_reporting: Dict[str, Any] = {}

        front_man: LangChainTokenCounter = self._make_counter(request_reporting, cloned=False, journal=None)
        front_man_callback: MagicMock = self._make_callback(own_tokens=30, own_requests=2)
        await front_man.report(front_man_callback, 20.0)

        late_external: LangChainTokenCounter = self._make_counter(request_reporting, cloned=True, journal=None,
                                                                  origin=self.EXTERNAL_FRONT_MAN_ORIGIN)
        late_external_callback: MagicMock = self._make_callback(own_tokens=15, own_requests=1)
        await late_external.report(late_external_callback, 3.0)

        total_accounting: Dict[str, Any] = request_reporting.get("total_token_accounting")
        # The late external's tokens still count toward the total ...
        self.assertEqual(total_accounting.get("total_tokens"), 45)
        # ... but the request latency remains the front man's.
        self.assertEqual(total_accounting.get("time_taken_in_seconds"), 20.0)

    async def test_report_flags_unattributed_tokens(self) -> None:
        """
        When the front man's subtree scalars exceed what completed scopes merged
        (e.g. agents cancelled mid-run), the total carries an explicit caveat
        instead of silently under-reporting.
        """
        request_reporting: Dict[str, Any] = {}

        front_man: LangChainTokenCounter = self._make_counter(request_reporting, cloned=False, journal=None)
        # Subtree heard 50 tokens, but only the front man's own 30 were merged:
        # a downstream agent died before its report().
        front_man_callback: MagicMock = self._make_callback(own_tokens=30, own_requests=2, subtree_tokens=50,
                                                            subtree_requests=3)
        await front_man.report(front_man_callback, 2.0)

        total_accounting: Dict[str, Any] = request_reporting.get("total_token_accounting")
        self.assertEqual(total_accounting.get("total_tokens"), 30)

        # Look through the caveats for the one about the 20 tokens no completed scope merged.
        found_unattributed_caveat: bool = False
        for caveat in total_accounting.get("caveats"):
            if "An additional 20 tokens" in caveat:
                found_unattributed_caveat = True
                break
        self.assertTrue(found_unattributed_caveat)

    async def test_report_network_message_gating(self) -> None:
        """
        Only the front man of the main network (single-element origin, non-cloned
        InvocationContext) writes the two complementary accounting messages:
        main network first, request total second.  Every other agent writes its
        per-agent subtree message, and everyone merges into request_reporting.
        """
        gating_cases: List[Tuple[List[Dict[str, Any]], bool, int]] = [
            # (origin, cloned, expected journal writes)
            (self.INTERNAL_AGENT_ORIGIN, False, 1),       # internal agent: agent message only
            (self.EXTERNAL_FRONT_MAN_ORIGIN, True, 1),    # direct-session external front man: agent message only
            (self.FRONT_MAN_ORIGIN, False, 2),            # main front man: main-network + total messages
        ]
        request_reporting: Dict[str, Any] = {}
        journal: Optional[MagicMock] = None
        for origin, cloned, expected_writes in gating_cases:
            request_reporting = {}
            journal = MagicMock()
            journal.write_message = AsyncMock()

            counter: LangChainTokenCounter = self._make_counter(request_reporting, cloned=cloned, journal=journal,
                                                                origin=origin)
            callback: MagicMock = self._make_callback(own_tokens=10, own_requests=1)
            await counter.report(callback, 1.0)

            self.assertEqual(journal.write_message.call_count, expected_writes, f"origin={origin} cloned={cloned}")
            # The merge into request_reporting happens for everyone.
            # DictionaryExtractor splits keys on ".", so this lookup only works for keys without a dot.
            request_reporting_extractor = DictionaryExtractor(request_reporting)
            self.assertEqual(request_reporting_extractor.get("total_token_accounting.total_tokens"), 10)

        # For the main front man (last case), the two messages are exactly the two
        # accounting entries of request_reporting, so the client-visible accounting
        # and the server log read the same.

        # The first message covers the main network only - no models breakdown,
        # same shape as the per-agent messages.
        main_message: AgentMessage = journal.write_message.call_args_list[0].args[0]
        self.assertIsInstance(main_message, AgentMessage)
        main_structure: Dict[str, Any] = main_message.structure
        self.assertEqual(main_structure, request_reporting.get("token_accounting"))
        self.assertEqual(main_structure.get("total_tokens"), 10)
        self.assertNotIn("models", main_structure.keys())
        self.assertIn("main agent network only", main_structure.get("caveats")[0])

        # The second message is the request total with the per-model breakdown.
        total_message: AgentMessage = journal.write_message.call_args_list[1].args[0]
        self.assertIsInstance(total_message, AgentMessage)
        total_structure: Dict[str, Any] = total_message.structure
        self.assertEqual(total_structure, request_reporting.get("total_token_accounting"))
        self.assertEqual(total_structure.get("total_tokens"), 10)
        self.assertIsNotNone(total_structure.get("models"))
        self.assertIn("Request total", total_structure.get("caveats")[0])

    def _make_counter(self, request_reporting: Dict[str, Any], cloned: bool, journal: Optional[Journal],
                      origin: Optional[List[Dict[str, Any]]] = None) -> LangChainTokenCounter:
        """
        Build a LangChainTokenCounter around a shared request_reporting dict.

        :param request_reporting: The request_reporting dict that every counter of one request shares
        :param cloned: True when the counter's InvocationContext is a clone (an external network's agent)
        :param journal: The journal the counter writes its accounting messages to, or None
        :param origin: The origin of the counter's agent; None means the main network's front man
        :return: A LangChainTokenCounter with a mock LLM and a mock InvocationContext
        """
        mock_invocation_context = MagicMock()
        mock_invocation_context.get_request_reporting.return_value = request_reporting
        mock_invocation_context.is_cloned.return_value = cloned

        counter_origin: List[Dict[str, Any]] = self.FRONT_MAN_ORIGIN
        if origin is not None:
            counter_origin = origin

        mock_llm = MagicMock()
        counter = LangChainTokenCounter(llm=mock_llm, invocation_context=mock_invocation_context, journal=journal,
                                        origin=counter_origin)
        return counter

    def _make_callback(self, own_tokens: int, own_requests: int, subtree_tokens: Optional[int] = None,
                       subtree_requests: Optional[int] = None) -> MagicMock:
        """
        Build a callback stand-in mirroring LlmTokenCallbackHandler semantics:
        models_token_dict covers only the agent's own calls, while the scalar
        totals cover the agent's whole subtree.

        :param own_tokens: Tokens of the agent's own LLM calls
        :param own_requests: Number of the agent's own LLM calls
        :param subtree_tokens: Tokens across the agent's whole subtree; None means the same as own_tokens
        :param subtree_requests: LLM calls across the agent's whole subtree; None means the same as own_requests
        :return: A MagicMock with the per-model dict and the scalar totals of an LlmTokenCallbackHandler
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

        callback.total_tokens = own_tokens
        if subtree_tokens is not None:
            callback.total_tokens = subtree_tokens
        callback.prompt_tokens = callback.total_tokens
        callback.completion_tokens = 0
        callback.successful_requests = own_requests
        if subtree_requests is not None:
            callback.successful_requests = subtree_requests
        callback.empty_responses = 0
        callback.total_cost = 0.0
        return callback
