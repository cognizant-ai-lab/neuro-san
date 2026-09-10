
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

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

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

    FRONT_MAN_ORIGIN = [{"tool": "front_man", "instantiation_index": 0}]
    INTERNAL_AGENT_ORIGIN = [
        {"tool": "front_man", "instantiation_index": 0},
        {"tool": "internal_agent", "instantiation_index": 0},
    ]
    EXTERNAL_FRONT_MAN_ORIGIN = [{"tool": "external_front_man", "instantiation_index": 0}]

    def _make_counter(self, request_reporting, cloned, journal, origin=None):
        """Build a LangChainTokenCounter around a shared request_reporting dict."""
        mock_invocation_context = MagicMock()
        mock_invocation_context.get_request_reporting.return_value = request_reporting
        mock_invocation_context.is_cloned.return_value = cloned
        return LangChainTokenCounter(
            llm=MagicMock(),
            invocation_context=mock_invocation_context,
            journal=journal,
            origin=origin if origin is not None else self.FRONT_MAN_ORIGIN,
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
        downstream = self._make_counter(request_reporting, cloned=False, journal=None,
                                        origin=self.INTERNAL_AGENT_ORIGIN)
        await downstream.report(self._make_callback(own_tokens=15, own_requests=1), 1.0)

        # The front man finishes last: 30 tokens / 2 calls of its own,
        # 45 tokens / 3 calls across its subtree.
        front_man = self._make_counter(request_reporting, cloned=False, journal=None)
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
        external = self._make_counter(request_reporting, cloned=True, journal=None,
                                      origin=self.EXTERNAL_FRONT_MAN_ORIGIN)
        await external.report(self._make_callback(own_tokens=15, own_requests=1), 1.0)

        # Before any main-network agent reports, the main accounting is an
        # explicit zero entry (not an empty dict), so a request that dies here
        # still logs well-formed accounting.
        assert request_reporting["token_accounting"]["total_tokens"] == 0
        assert "caveats" in request_reporting["token_accounting"]

        # The main network's front man finishes last: 30 tokens / 2 calls of its own.
        front_man = self._make_counter(request_reporting, cloned=False, journal=None)
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
    async def test_report_late_external_does_not_restamp_request_latency(self):
        """
        A cloned (external) agent completing after the front man - e.g. an
        "event" invocation that outlives the request - must not replace the
        request latency the front man stamped on the total.
        """
        request_reporting = {}

        front_man = self._make_counter(request_reporting, cloned=False, journal=None)
        await front_man.report(self._make_callback(own_tokens=30, own_requests=2), 20.0)

        late_external = self._make_counter(request_reporting, cloned=True, journal=None,
                                           origin=self.EXTERNAL_FRONT_MAN_ORIGIN)
        await late_external.report(self._make_callback(own_tokens=15, own_requests=1), 3.0)

        total_accounting = request_reporting["total_token_accounting"]
        # The late external's tokens still count toward the total ...
        assert total_accounting["total_tokens"] == 45
        # ... but the request latency remains the front man's.
        assert total_accounting["time_taken_in_seconds"] == 20.0

    @pytest.mark.asyncio
    async def test_report_flags_unattributed_tokens(self):
        """
        When the front man's subtree scalars exceed what completed scopes merged
        (e.g. agents cancelled mid-run), the total carries an explicit caveat
        instead of silently under-reporting.
        """
        request_reporting = {}

        front_man = self._make_counter(request_reporting, cloned=False, journal=None)
        # Subtree heard 50 tokens, but only the front man's own 30 were merged:
        # a downstream agent died before its report().
        await front_man.report(
            self._make_callback(own_tokens=30, own_requests=2, subtree_tokens=50, subtree_requests=3),
            2.0)

        total_accounting = request_reporting["total_token_accounting"]
        assert total_accounting["total_tokens"] == 30
        assert any("An additional 20 tokens" in caveat
                   for caveat in total_accounting["caveats"])

    @pytest.mark.asyncio
    async def test_report_network_message_gating(self):
        """
        Only the front man of the main network (single-element origin, non-cloned
        InvocationContext) writes the two complementary accounting messages:
        main network first, request total second.  Every other agent writes its
        per-agent subtree message, and everyone merges into request_reporting.
        """
        cases = [
            # (origin, cloned, expected journal writes)
            (self.INTERNAL_AGENT_ORIGIN, False, 1),       # internal agent: agent message only
            (self.EXTERNAL_FRONT_MAN_ORIGIN, True, 1),    # direct-session external front man: agent message only
            (self.FRONT_MAN_ORIGIN, False, 2),            # main front man: main-network + total messages
        ]
        for origin, cloned, expected_writes in cases:
            request_reporting = {}
            journal = MagicMock()
            journal.write_message = AsyncMock()

            counter = self._make_counter(request_reporting, cloned=cloned, journal=journal,
                                         origin=origin)
            await counter.report(self._make_callback(own_tokens=10, own_requests=1), 1.0)

            assert journal.write_message.call_count == expected_writes, \
                f"origin={origin} cloned={cloned}"
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
