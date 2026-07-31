
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
from typing import Awaitable
from typing import Dict
from typing import List
from typing import Union

from asyncio import Task
from asyncio import TimeoutError as AsyncTimeout
from asyncio import wait_for
from contextvars import Context
from contextvars import ContextVar
from contextvars import copy_context
from time import time

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages.ai import AIMessage

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.messages.origination import Origination
from neuro_san.internals.run_context.langchain.token_counting.get_llm_token_callback import get_llm_token_callback
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import llm_token_callback_var

# Keep a ContextVar for the origin info.  We do this because the
# langchain callbacks this stuff is based on also uses ContextVars
# and we want to be sure these are in sync.
# See: https://docs.python.org/3/library/contextvars.html
ORIGIN_INFO: ContextVar[str] = ContextVar('origin_info', default=None)

# Baseline for aggregated token stats.  Aggregations start from these zeros so
# request-level accounting always carries the standard keys even when no LLM
# usage was recorded - clients key off "total_tokens" being present
# (see TokenAccountingMessageFilter).
ZERO_TOKEN_STATS: Dict[str, Any] = {
    "total_tokens": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "successful_requests": 0,
    "empty_responses": 0,
    "total_cost": 0.0,
}

# Caveats shared by every token accounting message.
COMMON_CAVEATS: List[str] = [
    "Token counts are approximate and estimated using tiktoken.",
    "time_taken_in_seconds includes overhead from Langchain and Neuro SAN"
]

# Coverage statements for the two request-level accountings.
MAIN_NETWORK_CAVEAT: str = \
    "Token usage from agents of the main agent network only. " \
    "Usage from external agents is not included."
TOTAL_CAVEAT: str = \
    "Request total: includes token usage from external agents invoked via direct " \
    "sessions on this server. Usage from external agents reached over the network " \
    "is not included."


class LangChainTokenCounter:
    """
    Helps with per-llm means of counting tokens.
    Main entrypoint is count_tokens().

    Notes as to how each BaseLanguageModel/BaseChatModel should be configured
    are in get_callback_for_llm()
    """

    def __init__(self, llm: BaseLanguageModel,
                 invocation_context: InvocationContext,
                 journal: Journal,
                 origin: List[Dict[str, Any]]):
        """
        Constructor

        :param llm: The Llm to monitor for tokens
        :param invocation_context: The InvocationContext
        :param journal: The OriginatingJournal which through which this
                    will send token count AGENT messages
        :param origin: The origin that will be applied to all messages.
        """
        self.llm: BaseLanguageModel = llm
        self.invocation_context: InvocationContext = invocation_context
        self.journal: Journal = journal
        self.origin: List[Dict[str, Any]] = origin
        self.debug: bool = False

    async def count_tokens(self, awaitable: Awaitable, max_execution_seconds: float = None) -> Any:
        """
        Counts the tokens (if possible) from what happens inside the awaitable
        within a separate context.  If tokens are counted, they are added to
        the InvocationContext's request_reporting and sent over the message queue
        via the journal

        Recall awaitables are a full async method call with args.  That is, where you would expect to
                baz = await myinstance.foo(bar)
        you instead do
                baz = await token_counter.count_tokens(myinstance.foo(bar)).

        :param awaitable: The awaitable whose tokens we wish to count.
        :param max_execution_seconds: The maximum amount of time to execute the awaitable.
                        If None, the awaitable is executed to completion.
        :return: Whatever the awaitable would return
        """

        retval: Any = None
        llm_factory: ContextTypeLlmFactory = self.invocation_context.get_llm_factory()
        llm_infos: Dict[str, Any] = llm_factory.llm_infos
        # Take a time stamp so we measure another thing people care about - latency.
        start_time: float = time()

        # Attempt to count tokens/costs while invoking the agent.
        # The means by which this happens is on a per-LLM basis, so get the right hook
        # given the LLM we've got.
        callback: AsyncCallbackHandler = None
        # Record origin information in our own context var so we can associate
        # with the langchain callback context vars more easily.
        origin_str: str = Origination.get_full_name_from_origin(self.origin)
        ORIGIN_INFO.set(origin_str)

        # Use the context manager to count tokens as per
        #   https://python.langchain.com/docs/how_to/llm_token_usage_tracking/#using-callbacks
        #
        # How the counting behaves:
        # * The context manager sets a fresh handler in a ContextVar which langchain's
        #   register_configure_hook() attaches to runs as an *inheritable* callback.
        #   Since descendant agent invocations merge the ambient config (see
        #   RunContextRunnable.run_it()), this agent's handler also receives events for
        #   LLM calls made by all downstream agents - including agents of same-server
        #   external networks invoked through direct sessions. The handler's scalar
        #   totals (total_tokens et al) are therefore cumulative over this agent's
        #   whole subtree, and a front man's totals cover the entire request.
        # * The handler's models_token_dict is different: it only counts LLM calls
        #   belonging to this agent itself (see LlmTokenCallbackHandler._is_own_call()),
        #   so that report() below can accumulate per-model stats into request_reporting
        #   with each call counted exactly once, no matter how deeply agents nest.
        # * External agents on *remote* servers handle their own requests in a separate
        #   context and are not seen by this handler at all.
        # Note on cancellation: if this task is cancelled outright (e.g. client
        # disconnect), CancelledError propagates and report() below never runs -
        # by design, since journaling from a cancelled task would fail anyway.
        # The timeout path does report.  Descendant scopes cancelled mid-run are
        # accounted for by the "unattributed tokens" caveat the front man adds
        # in report().
        timed_out: bool = False
        with get_llm_token_callback(llm_infos) as callback:
            # Create a new context for different ContextVar values
            # and use the create_task() to run within that context.
            new_context: Context = copy_context()
            task: Task = new_context.run(self.create_task, awaitable)
            try:
                retval = await wait_for(task, max_execution_seconds)
            except AsyncTimeout:
                # Per docs for wait_for(), the task is already cancelled, so the
                # task's own final journal.write_message(AIMessage(...)) never ran.
                # Synthesize that final AIMessage here — before report() below — so
                # the journal order matches the normal-completion path:
                #   streamed events -> final AIMessage -> token accounting.
                timeout_output: str = (
                    f"Agent timed out: max_execution_seconds={max_execution_seconds}s exceeded."
                )
                if self.journal is not None:
                    await self.journal.write_message(AIMessage(timeout_output))
                retval = None
                timed_out = True

        # Figure out how much time our agent took.
        end_time: float = time()
        time_taken_in_seconds: float = end_time - start_time

        await self.report(callback, time_taken_in_seconds)

        if timed_out:
            # Re-raise so the caller can handle/log the timeout.
            raise AsyncTimeout(
                f"Agent '{origin_str}' exceeded max_execution_seconds={max_execution_seconds}s"
            )

        return retval

    def create_task(self, awaitable: Awaitable) -> Task:
        """
        Riffed from:
        https://stackoverflow.com/questions/78659844/async-version-of-context-run-for-context-vars-in-python-asyncio
        """
        executor: AsyncioExecutor = self.invocation_context.get_asyncio_executor()
        origin_str: str = ORIGIN_INFO.get()
        task: Task = executor.create_task(awaitable, origin_str)

        if self.debug:
            # Print to be sure we have a different callback object.
            oai_call = llm_token_callback_var.get()
            print(f"origin is {origin_str} callback var is {id(oai_call)}")

        return task

    async def report(self, callback: AsyncCallbackHandler, time_taken_in_seconds: float):
        """
        Report on the token accounting results of the callback

        :param callback: An AsyncCallbackHandler or BaseCallbackHandle instance that contains token counting information
        :param time_taken_in_seconds: The amount of time the awaitable took in count_tokens()
        """

        # Accumulate what we learned about tokens to request reporting.
        #
        # Every agent's count_tokens() ends up here when its invocation completes.
        # callback.models_token_dict contains per-model stats for only this agent's
        # own LLM calls (see LlmTokenCallbackHandler), so merging each agent's
        # contribution counts every LLM call in the request exactly once, no matter
        # how deeply agents nest.  This includes agents of same-server external
        # networks invoked via direct sessions, whose cloned InvocationContexts
        # intentionally share this request_reporting dictionary (see
        # SessionInvocationContext.safe_shallow_copy()).
        # Since the front man is always the last to finish, by the time it exits,
        # the request reporting covers the whole request and is ready to report.
        #
        # Two accountings are kept in request_reporting - in this order, so the
        # server log prints the main network first and the request total last:
        # * "token_accounting": usage from agents of the main (top-level) network
        #   only, as this key's caveat has always advertised.  No per-model breakdown.
        # * "total_token_accounting": the request total - everything that ran
        #   in-process, including same-server external agents - with the
        #   per-model breakdown.
        # The front man of the main network streams these two dictionaries verbatim
        # as its two accounting messages, so the server log and the client-visible
        # messages read the same.
        request_reporting: Dict[str, Any] = self.invocation_context.get_request_reporting()
        total_accounting: Dict[str, Any] = request_reporting.get("total_token_accounting", {})
        models_token_dict: Dict[str, Any] = \
            self.merge_dicts(total_accounting.get("models", {}), callback.models_token_dict)

        # The request latency is owned by the main network's front man - always the
        # last main-network agent to finish.  A cloned (external) agent completing
        # late (e.g. "event" invocations that outlive the request) must not re-stamp
        # it with its own duration.
        total_time: float = time_taken_in_seconds
        if self.invocation_context.is_cloned():
            total_time = total_accounting.get("time_taken_in_seconds", time_taken_in_seconds)

        network_token_dict: Dict[str, Any] = self.sum_all_tokens(models_token_dict, total_time)
        # Provide sligtly different "caveats" for the network token accounting.
        network_token_dict["caveats"] = [TOTAL_CAVEAT] + COMMON_CAVEATS

        # Maintain the accounting covering only the main (top-level) agent network.
        # Agents of external networks invoked via direct sessions run on cloned
        # InvocationContexts, so they contribute to the totals but not to this one.
        main_accounting: Dict[str, Any] = request_reporting.get("token_accounting", {})
        if not self.invocation_context.is_cloned():
            # Add this agent's own contribution (summed across its per-model stats)
            # to the scalars accumulated so far.  The merge also sums the previous
            # time_taken_in_seconds, but that is not a summable metric, so it is
            # simply re-stamped below with the latest reporter's - which for the
            # last one out, the front man, is the whole request's latency.
            contribution: Dict[str, Any] = self.sum_all_tokens(callback.models_token_dict,
                                                               time_taken_in_seconds)
            main_accounting = self.merge_dicts(main_accounting, contribution)
            main_accounting["time_taken_in_seconds"] = time_taken_in_seconds
            main_accounting["caveats"] = [MAIN_NETWORK_CAVEAT] + COMMON_CAVEATS
        elif not main_accounting:
            # An external agent completed before any main-network agent reported.
            # Publish an explicit zero entry rather than an empty dictionary.
            main_accounting = self.sum_all_tokens({}, 0.0)
            main_accounting["caveats"] = [MAIN_NETWORK_CAVEAT] + COMMON_CAVEATS

        # Assignment preserves key insertion order (main first, total last, as the
        # first reporter established) so the server log always prints them that way.
        request_reporting["token_accounting"] = main_accounting
        request_reporting["total_token_accounting"] = \
            {**network_token_dict, "models": models_token_dict}

        # Figure out whether we are the front man of the main network:
        # * Only front men sit at the root of the origin path (single-element origin).
        # * Front men of same-server external networks invoked via direct sessions
        #   also have single-element origins, but they run on a cloned InvocationContext.
        is_main_front_man: bool = \
            self.origin is not None and len(self.origin) == 1 and \
            not self.invocation_context.is_cloned()

        if is_main_front_man:
            # This front man's scalar totals cover everything its handler heard
            # (its whole subtree).  Anything above what completed scopes merged
            # into the total (e.g. LLM calls of agents cancelled mid-run) is
            # unattributed - say so rather than silently under-reporting.
            total_token_dict: Dict[str, Any] = request_reporting["total_token_accounting"]
            unattributed_tokens: int = callback.total_tokens - total_token_dict["total_tokens"]
            if unattributed_tokens > 0:
                total_token_dict["caveats"] = total_token_dict["caveats"] + [
                    f"An additional {unattributed_tokens} tokens were used by agents "
                    "that did not complete and are not included."
                ]

        if self.journal is not None:
            if is_main_front_man:
                # The front man of the main network reports the two request-level
                # accountings as two complementary messages - main network first,
                # request total second - each stating its coverage in its caveats.
                # External front men do not do this: their tokens are already merged into
                # the shared request_reporting above, and a request-level message from them
                # mid-request would report a partial (and potentially sibling-polluted) total.
                await self.journal.write_message(
                    AgentMessage(structure=request_reporting["token_accounting"]))
                await self.journal.write_message(
                    AgentMessage(structure=request_reporting["total_token_accounting"]))
            else:
                # Every other agent reports the token usage of its own subtree.
                agent_token_dict: Dict[str, Any] = \
                    self._generate_agent_token_dict(callback, time_taken_in_seconds)
                await self.journal.write_message(AgentMessage(structure=agent_token_dict))

    def _generate_agent_token_dict(
            self,
            callback: Union[AsyncCallbackHandler, BaseCallbackHandler],
            time_taken_in_seconds: float,
    ) -> Dict[str, Any]:
        """
        Generate the token counting dictionary for journals

        :param callback: An AsyncCallbackHandler or BaseCallbackHandler instance that contains
                            token counting information
        :param time_taken_in_seconds: The amount of time the awaitable took in count_tokens()
        :param agent_name: Name of the agent responsible for the token dictionary
        :return: Formatted token dictionary
        """

        # Organize the token dict for each agent to be the same format
        agent_token_dict = {
            "total_tokens": callback.total_tokens,
            "prompt_tokens": callback.prompt_tokens,
            "completion_tokens": callback.completion_tokens,
            "successful_requests": callback.successful_requests,
            "empty_responses": getattr(callback, "empty_responses", 0),
            "total_cost": callback.total_cost,
            "time_taken_in_seconds": time_taken_in_seconds,
            "caveats": [
                "Token usage is tracked at the agent level. "
                "Counts include usage from any downstream agents called on this agent's behalf."
            ] + COMMON_CAVEATS
        }

        return agent_token_dict

    def sum_all_tokens(self, token_dict: Dict[str, Any], time_value: float) -> Dict[str, Any]:

        """
        Sum all token metrics across providers and models, **excluding time**.
        :param token_dict: Models token dict to aggregate into network stats
        :param time_value: Time taken for frontman to finish
        :return: Token stats of the entire network, either cumulative or single iteration.
                Always contains the standard metric keys (zeros when there is
                nothing to aggregate) so downstream consumers can rely on them.
        """
        aggregated: Dict[str, Any] = dict(ZERO_TOKEN_STATS)
        for models in token_dict.values():
            for model_stats in models.values():
                for metric, value in model_stats.items():
                    if metric != "time_taken_in_seconds":
                        aggregated[metric] = aggregated.get(metric, 0) + value

        aggregated["time_taken_in_seconds"] = time_value

        return aggregated

    def merge_dicts(self, dict_1, dict_2):
        """
        Recursively merge two dictionaries.

        If both dictionaries contain the same key:
        - If the corresponding values are dictionaries, they are merged recursively.
        - Otherwise, the values are assumed to be numeric and are summed.

        Keys that exist only in one dictionary are carried over unchanged.

        :param dict_1: The base dictionary.
        :param dict_2: The dictionary whose values will be merged into `dict_1`.
        :return: A new dictionary containing the merged result.
        """
        result: Dict[str, Any] = dict(dict_1)  # start with dict_1
        for key, value in dict_2.items():
            if key in result:
                if isinstance(result[key], dict) and isinstance(value, dict):
                    # recursively merge nested dicts
                    result[key] = self.merge_dicts(result[key], value)
                else:
                    # assume values are numbers, sum them
                    result[key] += value
            else:
                result[key] = value
        return result
