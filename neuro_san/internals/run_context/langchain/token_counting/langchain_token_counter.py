
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

from typing import Any
from typing import Awaitable
from typing import Dict
from typing import List
from typing import Union

from asyncio import Task
from contextvars import Context
from contextvars import ContextVar
from contextvars import copy_context
from time import time

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.language_models.base import BaseLanguageModel

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.originating_journal import OriginatingJournal
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.messages.origination import Origination
from neuro_san.internals.run_context.langchain.token_counting.get_llm_token_callback import get_llm_token_callback
from neuro_san.internals.run_context.langchain.token_counting.get_llm_token_callback import llm_token_callback_var

# Keep a ContextVar for the origin info.  We do this because the
# langchain callbacks this stuff is based on also uses ContextVars
# and we want to be sure these are in sync.
# See: https://docs.python.org/3/library/contextvars.html
ORIGIN_INFO: ContextVar[str] = ContextVar('origin_info', default=None)


class LangChainTokenCounter:
    """
    Helps with per-llm means of counting tokens.
    Main entrypoint is count_tokens().

    Notes as to how each BaseLanguageModel/BaseChatModel should be configured
    are in get_callback_for_llm()
    """

    def __init__(self, llm: BaseLanguageModel,
                 invocation_context: InvocationContext,
                 journal: OriginatingJournal):
        """
        Constructor

        :param llm: The Llm to monitor for tokens
        :param invocation_context: The InvocationContext
        :param journal: The OriginatingJournal which through which this
                    will send token count AGENT messages
        """
        self.llm: BaseLanguageModel = llm
        self.invocation_context: InvocationContext = invocation_context
        self.journal: OriginatingJournal = journal
        self.debug: bool = False

    async def count_tokens(self, awaitable: Awaitable) -> Any:
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
        origin: List[Dict[str, Any]] = self.journal.get_origin()
        origin_str: str = Origination.get_full_name_from_origin(origin)
        ORIGIN_INFO.set(origin_str)

        # Use the context manager to count tokens as per
        #   https://python.langchain.com/docs/how_to/llm_token_usage_tracking/#using-callbacks
        #
        # Caveats:
        # * In using this context manager approach, any tool that is called
        #   also has its token counts contributing to its callers for better or worse.
        # * As of 2/21/25, it seems that tool-calling agents (branch nodes) are not
        #   registering their tokens correctly. Not sure if this is a bug in langchain
        #   or there is something we are not doing in that scenario that we should be.
        # * As of 8/21/25, placing the journaling callback in the invoke config instead of llm
        #   appears to change the context manager’s behavior. The returned tokens from callback
        #   are now limited to the calling agent only, and no longer include those
        #   from downstream (chained) agents. However, `models_token_dict` is added
        #   to the `LlmTokenCallbackHandler` to collect token stats of each model call.
        with get_llm_token_callback(llm_infos) as callback:
            # Create a new context for different ContextVar values
            # and use the create_task() to run within that context.
            new_context: Context = copy_context()
            task: Task = new_context.run(self.create_task, awaitable)
            retval = await task

        # Figure out how much time our agent took.
        end_time: float = time()
        time_taken_in_seconds: float = end_time - start_time

        await self.report(callback, time_taken_in_seconds)

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
        # For now we just overwrite the one key because we know
        # the last one out will be the front man, and as of 2/21/25 his stats
        # are cumulative.  At some point we might want a finer-grained breakdown
        # that perhaps contributes to a service/er-wide periodic token stats breakdown
        # of some kind.  For now, get something going.
        #
        # Update (8/21/25):
        # Placing the journaling callback in the invoke config instead of llm changes the context
        # manager’s behavior. The returned tokens from the callback are now limited
        # to the calling agent only, not downstream (chained) agents.
        # Instead, `models` have been added to `request_reporting["token_accounting"]` to collect per-model stats
        # which are combined into network token stats.
        # Since the frontman is always the last to finish, by the time it exits,
        # `request_reporting["token_accounting"]` is complete and ready to report.
        request_reporting: Dict[str, Any] = self.invocation_context.get_request_reporting()
        token_accounting: Dict[str, Any] = request_reporting.get("token_accounting", {})
        models_token_dict: Dict[str, Any] = \
            self.merge_dicts(token_accounting.get("models", {}), callback.models_token_dict)
        network_token_dict: Dict[str, Any] = self.sum_all_tokens(models_token_dict, time_taken_in_seconds)
        # Provide sligtly different "caveats" for the network token accounting.
        network_token_dict["caveats"] = [
            "External agent token usage is not included.",
            "Token counts are approximate and estimated using tiktoken.",
            "time_taken_in_seconds includes overhead from Langchain and Neuro-SAN"
        ]
        request_reporting["token_accounting"] = \
            {**network_token_dict, "models": models_token_dict}

        # Token counting results are collected in the callback.
        # Create a token counting dictionary for each agent
        agent_token_dict: Dict[str, Any] = self._generate_agent_token_dict(callback, time_taken_in_seconds)
        if self.journal is not None:
            # We actually have a token dictionary to report, so go there.
            agent_message = AgentMessage(structure=agent_token_dict)
            await self.journal.write_message(agent_message)
            # For frontman (origin with no ".") write both network token dict and model token dict
            if "." not in ORIGIN_INFO.get():
                network_token_message = AgentMessage(structure=request_reporting["token_accounting"])
                await self.journal.write_message(network_token_message)

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
            "total_cost": callback.total_cost,
            "time_taken_in_seconds": time_taken_in_seconds,
            "caveats": [
                "Token usage is tracked at the agent level.",
                "Token counts are approximate and estimated using tiktoken.",
                "time_taken_in_seconds includes overhead from Langchain and Neuro-SAN"
            ]
        }

        return agent_token_dict

    def sum_all_tokens(self, token_dict: Dict[str, Any], time_value: float) -> Dict[str, Any]:

        """
        Sum all token metrics across providers and models, **excluding time**.
        :param token_dict: Models token dict to aggregate into network stats
        :param time_value: Time taken for frontman to finish
        :return: Token stats of the entire network, either cumulative or single iteration
        """
        aggregated: Dict[str, Any] = {}
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
