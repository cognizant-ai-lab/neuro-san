
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
from typing import Tuple
from typing import Type
from typing import Union

from asyncio import Task
from contextvars import Context
from contextvars import ContextVar
from contextvars import copy_context
from time import time

from langchain_community.callbacks.openai_info import OpenAICallbackHandler
from langchain_community.callbacks.manager import get_openai_callback
from langchain_community.callbacks.manager import openai_callback_var
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.language_models.base import BaseLanguageModel

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from leaf_common.config.resolver_util import ResolverUtil

from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.originating_journal import OriginatingJournal
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.messages.origination import Origination
from neuro_san.internals.run_context.langchain.token_counting.get_llm_token_callback import get_llm_token_callback
from neuro_san.internals.run_context.langchain.token_counting.get_llm_token_callback import llm_token_callback_var
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import LlmTokenCallbackHandler


# Keep a ContextVar for the origin info.  We do this because the
# langchain callbacks this stuff is based on also uses ContextVars
# and we want to be sure these are in sync.
# See: https://docs.python.org/3/library/contextvars.html
ORIGIN_INFO: ContextVar[str] = ContextVar('origin_info', default=None)

# Keep a single lazy resolution of OpenAI chat model types.
OPENAI_CHAT_TYPES: Tuple[Type[Any], ...] = ResolverUtil.create_type_tuple([
                                                "langchain_openai.chat_models.base.ChatOpenAI",
                                                "langchain_openai.chat_models.azure.AzureChatOpenAI",
                                           ])


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

        # Take a time stamp so we measure another thing people care about - latency.
        start_time: float = time()

        # Attempt to count tokens/costs while invoking the agent.
        # The means by which this happens is on a per-LLM basis, so get the right hook
        # given the LLM we've got.
        callback: Union[AsyncCallbackHandler, BaseCallbackHandler] = None
        token_counter_context_manager = self.get_callback_for_llm(self.llm)

        if token_counter_context_manager is not None:

            # Record origin information in our own context var so we can associate
            # with the langchain callback context vars more easily.
            origin: List[Dict[str, Any]] = self.journal.get_origin()
            origin_str: str = Origination.get_full_name_from_origin(origin)
            ORIGIN_INFO.set(origin_str)

            old_callback: Union[AsyncCallbackHandler, BaseCallbackHandler] = None
            callback_var: ContextVar = self.get_context_var_for_llm(self.llm)
            if callback_var is not None:
                old_callback = callback_var.get()

            # Use the context manager to count tokens as per
            #   https://python.langchain.com/docs/how_to/llm_token_usage_tracking/#using-callbacks
            #
            # Caveats:
            # * In using this context manager approach, any tool that is called
            #   also has its token counts contributing to its callers for better or worse.
            # * As of 2/21/25, it seems that tool-calling agents (branch nodes) are not
            #   registering their tokens correctly. Not sure if this is a bug in langchain
            #   or there is something we are not doing in that scenario that we should be.
            with token_counter_context_manager() as callback:
                # Create a new context for different ContextVar values
                # and use the create_task() to run within that context.
                new_context: Context = copy_context()
                task: Task = new_context.run(self.create_task, awaitable)
                retval = await task

            if callback_var is not None:
                callback_var.set(old_callback)
        else:
            # No token counting was available for the LLM, but we still need to invoke.
            retval = await awaitable

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
            oai_call = openai_callback_var.get()
            print(f"origin is {origin_str} callback var is {id(oai_call)}")

        return task

    async def report(self, callback: Union[AsyncCallbackHandler, BaseCallbackHandler], time_taken_in_seconds: float):
        """
        Report on the token accounting results of the callback

        :param callback: An AsyncCallbackHandler or BaseCallbackHandle instance that contains token counting information
        :param time_taken_in_seconds: The amount of time the awaitable took in count_tokens()
        """
        # Token counting results are collected in the callback, if there are any.
        # Different LLMs can count things in different ways, so normalize.
        token_dict: Dict[str, Any] = self.normalize_token_count(callback, time_taken_in_seconds)
        if token_dict is None or not bool(token_dict):
            return

        # Accumulate what we learned about tokens to request reporting.
        # For now we just overwrite the one key because we know
        # the last one out will be the front man, and as of 2/21/25 his stats
        # are cumulative.  At some point we might want a finer-grained breakdown
        # that perhaps contributes to a service/er-wide periodic token stats breakdown
        # of some kind.  For now, get something going.
        request_reporting: Dict[str, Any] = self.invocation_context.get_request_reporting()
        request_reporting["token_accounting"] = token_dict

        if self.journal is not None:
            # We actually have a token dictionary to report, so go there.
            agent_message = AgentMessage(structure=token_dict)
            await self.journal.write_message(agent_message)

    @staticmethod
    def get_callback_for_llm(llm: BaseLanguageModel) -> Any:
        """
        :param llm: A BaseLanguageModel returned from an LlmFactory.
        :return: A handle to a no-args function, that when called will
                open up a context manager for token counting.
                If not an OpenAI or Anthropic model, use context manager
                for LlmTokenCallbackHandler, which also gets token usage
                from "usage_metadata" but give "total_cost" = 0.
        """

        if isinstance(llm, OPENAI_CHAT_TYPES):
            # Use the context manager to count tokens as per
            #   https://python.langchain.com/docs/how_to/llm_token_usage_tracking/#using-callbacks
            # Notes:
            #   * ChatOpenAI needs to have stream_usage=True configured
            #     in order to get good token info back reliably.
            #   * AzureChatOpenAI needs to have model_kwargs.stream_options.include_usage=True
            #     configured in order to get good token info back reliably.
            return get_openai_callback

        # * ChatAnthropic needs to have stream_usage=True configured
        #   in order to get good token info back reliably.
        #   Per class docs this is on by default.

        # Open up a context manager for LlmTokenCallbackHandler, which also gets token usage
        # from "usage_metadata"
        # # Cost for Anthropic models can be determined as we import the lookup table
        # from https://python.langchain.com/api_reference/_modules/langchain_community/callbacks/
        # bedrock_anthropic_callback.html#BedrockAnthropicTokenUsageCallbackHandler
        # for non "claude" model "total_cost" = 0.0.
        return get_llm_token_callback

    @staticmethod
    def get_context_var_for_llm(llm: BaseLanguageModel) -> ContextVar:
        """
        :param llm: A BaseLanguageModel returned from an LlmFactory.
        :return: A ContextVar that corresponds to where token counting callback
                information is going.
                If not an OpenAI or Anthropic model, use llm_token_callback_var.
        """

        if isinstance(llm, OPENAI_CHAT_TYPES):
            return openai_callback_var

        # Collect tokens for models other than OpenAI
        return llm_token_callback_var

    @staticmethod
    def normalize_token_count(callback: Union[AsyncCallbackHandler, BaseCallbackHandler],
                              time_taken_in_seconds: float
                              ) -> Dict[str, Any]:
        """
        Normalizes the values in the token counting callback into a standard dictionary

        :param callback: An AsyncCallbackHandler or BaseCallbackHandler instance that contains
                            token counting information
        :param time_taken_in_seconds: The amount of time the awaitable took in count_tokens()
        """

        token_dict: Dict[str, Any] = {
            "time_taken_in_seconds": time_taken_in_seconds
        }
        if callback is None:
            return token_dict

        if isinstance(
            callback,
            (OpenAICallbackHandler, LlmTokenCallbackHandler)
        ):
            # So far these two instances share the same reporting structure
            token_dict = {
                "total_tokens": callback.total_tokens,
                "prompt_tokens": callback.prompt_tokens,
                "completion_tokens": callback.completion_tokens,
                "successful_requests": callback.successful_requests,
                "total_cost": callback.total_cost,
                "time_taken_in_seconds": time_taken_in_seconds,
                "caveats": [
                    "Token usage is tracked at the agent level.",
                    "Token counts are approximate and estimated using tiktoken.",
                ]
            }

        return token_dict
