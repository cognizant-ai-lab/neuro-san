
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
from typing import Tuple
from typing import Type
from typing import Union

import traceback

from pydantic import ConfigDict

from langchain_classic.callbacks.tracers.logging import LoggingCallbackHandler
from langchain_core.agents import AgentFinish
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.runnables.base import Runnable
from langchain_core.runnables.config import ensure_config
from langchain_core.runnables.config import merge_configs
from langchain_core.runnables.utils import Input
from langchain_core.runnables.utils import Output

from leaf_common.config.resolver_util import ResolverUtil

from neuro_san.internals.errors.error_detector import ErrorDetector
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.origination import Origination
from neuro_san.internals.run_context.interfaces.tool_caller import ToolCaller
from neuro_san.internals.run_context.langchain.journaling.journaling_callback_handler import JournalingCallbackHandler
from neuro_san.internals.run_context.langchain.token_counting.langchain_token_counter import LangChainTokenCounter
from neuro_san.internals.run_context.langchain.tracing.neuro_san_runnable import NeuroSanRunnable
from neuro_san.internals.run_context.langchain.util.api_key_error_check import ApiKeyErrorCheck

MINUTES: float = 60.0

# Lazily import specific errors from llm providers
RATE_LIMIT_ERROR_TYPES: Tuple[Type[Any], ...] = ResolverUtil.create_type_tuple([
                                            "openai.RateLimitError",
                                            "anthropic.RateLimitError",
                                            "google.genai._interactions.RateLimitError",
                                         ])

# Lazily import specific errors from llm providers
API_ERROR_TYPES: Tuple[Type[Any], ...] = ResolverUtil.create_type_tuple([
                                            "openai.APIError",
                                            "anthropic.APIError",
                                            "langchain_google_genai.chat_models.ChatGoogleGenerativeAIError",
                                         ])


class RunContextRunnable(NeuroSanRunnable):
    """
    RunnablePassthrough implementation that intercepts journal messages
    """

    # Declarations of member variables here satisfy Pydantic style,
    # which is a type validator that langchain is based on which
    # is able to use JSON schema definitions to validate fields.
    agent_chain: Runnable

    primary_llm: BaseLanguageModel

    journal: Journal

    tool_caller: ToolCaller

    error_detector: ErrorDetector

    session_id: str

    # This guy needs to be a pydantic class and in order to have
    # a non-pydantic Journal as a member, we need to do this.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # pylint: disable=redefined-builtin
    async def run_it(self, inputs: Input) -> Output:
        """
        Transform a single input into an output.

        Args:
            inputs: The input to the `Runnable`.

        Returns:
            The output of the `Runnable`.
        """

        # Create an agent executor and invoke it with the most recent human message
        # as input.
        agent_spec: Dict[str, Any] = self.tool_caller.get_agent_tool_spec()

        max_execution_seconds: float = agent_spec.get("max_execution_seconds", 2.0 * MINUTES)

        # Langchain `create_agent` uses LangGraph under the hood, which has a default recursion limit of 10,000.
        # Even though it is called "recursion limit", it is actually more of a step ("super-step") limit for
        # the entire graph execution, which includes all calls to tools and LLMs.
        # Nodes that run in parallel are part of the same super-step,
        # while nodes that run sequentially belong to separate super-steps.
        # Note that the documentation states that the default is 1,000 but the code itself has a default of 10,000.
        #
        # Documentation:
        # https://docs.langchain.com/oss/python/langgraph/graph-api#recursion-limit
        # https://docs.langchain.com/oss/python/langgraph/graph-api#graphs
        #
        # Code:
        # https://github.com/langchain-ai/langchain/blob/master/libs/langchain_v1/langchain/agents/factory.py
        # https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/pregel/_loop.py
        max_iterations: int = agent_spec.get("max_iterations")
        if max_iterations is not None:
            self.logger.warning(
                "Agent config for '%s' of '%s' network contains 'max_iterations' which is deprecated. "
                "Please use 'max_steps' instead.",
                self.tool_caller.get_name(),
                self.invocation_context.get_agent_name()
            )
        # Calling the parameter "max_steps" going forward to avoid confusion with the "max_iterations" parameter.
        # Only fall back to "max_iterations" if "max_steps" was not explicitly provided.
        # Default is 10,000 to match the default recursion limit in LangGraph.
        max_steps: int = agent_spec.get("max_steps") or max_iterations or 10_000

        # Create the list of callbacks to pass when invoking
        parent_origin: List[Dict[str, Any]] = self.origin
        base_journal: Journal = self.invocation_context.get_journal()
        origination: Origination = self.invocation_context.get_origination()
        callbacks: List[BaseCallbackHandler] = [
            JournalingCallbackHandler(self.journal, base_journal, parent_origin, origination)
        ]

        # Consult the agent spec for level of verbosity as it pertains to callbacks.
        agent_spec: Dict[str, Any] = self.tool_caller.get_agent_tool_spec()
        verbose: Union[bool, str] = agent_spec.get("verbose", False)
        if isinstance(verbose, str) and verbose.lower() in ("true", "extra", "logging"):
            # This particular class adds a *lot* of very detailed messages
            # to the logs.  Add this because some people are interested in it.
            callbacks.append(LoggingCallbackHandler(self.logger))

        # Get the number of attempts from the spec.
        max_attempts: int = agent_spec.get("max_attempts", 3)
        max_attempts = max(max_attempts, 1)

        # Prepare our own runnable config
        runnable_config: Dict[str, Any] = self.prepare_runnable_config(callbacks=callbacks,
                                                                       recursion_limit=max_steps)
        # Need to merge in the existing config with the one that we just created so the notion
        # of "parent_run_id" gets preserved.
        runnable_config = merge_configs(ensure_config(), runnable_config)

        # Attempt to count tokens/costs while invoking the agent.
        token_counter = LangChainTokenCounter(self.primary_llm, self.invocation_context, self.journal, self.origin)
        await token_counter.count_tokens(self.invoke_agent_chain(inputs, runnable_config, max_attempts),
                                         max_execution_seconds)

        return inputs

    # pylint: disable=too-many-locals,too-many-statements
    async def invoke_agent_chain(self, inputs: Dict[str, Any], runnable_config: Dict[str, Any], max_attempts: int):
        """
        Set the agent in motion

        :param inputs: The inputs to the agent_executor
        :param runnable_config: The runnable_config to send to the agent_executor
        :param max_attempts: The maximum number of attempts to make allowing for errors of any kind.
        """
        chain_result: Union[Dict[str, Any], AgentFinish, AIMessage] = None
        attempts: int = max_attempts
        exception: Exception = None
        backtrace: str = None
        while chain_result is None and attempts > 0:
            try:
                chain_result: Dict[str, Any] = await self.agent_chain.ainvoke(input=inputs, config=runnable_config)
            except RATE_LIMIT_ERROR_TYPES as rate_limit_error:
                self.logger.warning("retrying from RateLimit error %s(%s)",
                                    rate_limit_error.__class__.__name__,
                                    str(rate_limit_error))
                attempts = attempts - 1
                exception = rate_limit_error
            except API_ERROR_TYPES as api_error:
                backtrace = traceback.format_exc()
                message: str = None
                if not ApiKeyErrorCheck.check_for_internal_error(backtrace):
                    # Does not look like internal LLM stack error:
                    message = ApiKeyErrorCheck.check_for_api_key_exception(api_error)
                if message is not None:
                    # Construct a uniform message to return to the client
                    # indicating that they likely have an API key problem,
                    # rather than retrying and hitting the same error again.
                    exception = None
                    backtrace = None
                    chain_result = {
                        "output": message
                    }
                    # Log the error with technical details for debugging purposes,
                    # but we are returning a more user-friendly message to the client.
                    # get_safe_log_message() redacts pydantic ValidationError input values
                    # so user-supplied API key material can't leak into server logs.
                    self.logger.error("API KEY error detected: %s",
                                      ApiKeyErrorCheck.get_safe_log_message(api_error))
                    break
                # Continue with regular retry logic:
                self.logger.warning("retrying from %s", api_error.__class__.__name__)
                attempts = attempts - 1
                exception = api_error
            except KeyError as key_error:
                self.logger.warning("retrying from KeyError")
                attempts = attempts - 1
                exception = key_error
                backtrace = traceback.format_exc()
            except ValueError as value_error:
                response = str(value_error)
                find_string = "An output parsing error occurred. " + \
                              "In order to pass this error back to the agent and have it try again, " + \
                              "pass `handle_parsing_errors=True` to the AgentExecutor. " + \
                              "This is the error: Could not parse LLM output: `"
                if response.startswith(find_string):
                    # Agent is returning good stuff, but langchain is erroring out over it.
                    # From: https://github.com/langchain-ai/langchain/issues/1358#issuecomment-1486132587
                    # Per thread consensus, this is hacky and there are better ways to go,
                    # but removes immediate impediments.
                    chain_result = {
                        "output": response.removeprefix(find_string).removesuffix("`")
                    }
                else:
                    self.logger.warning("retrying from ValueError")
                    attempts = attempts - 1
                    exception = value_error
                    backtrace = traceback.format_exc()
            # pylint: disable=broad-exception-caught
            except Exception as exception_error:
                # This catches any errors from running middlewares and also error form exceeding the recursion_limit.
                self.logger.error("Got exception in  %s. Error: %s",
                                  self.__class__.__name__,
                                  exception_error,
                                  )
                # These are likely real issues and non-retryable.
                attempts = 0
                exception = exception_error
                backtrace = traceback.format_exc()

        output: str = self.parse_chain_result(chain_result, exception, backtrace)
        return_message: BaseMessage = AIMessage(output)

        # Chat history is updated in write_message
        await self.journal.write_message(return_message)

    def parse_chain_result(self, chain_result: Union[Dict[str, Any], AgentFinish, AIMessage],
                           exception: Exception, backtrace: str) -> str:
        """
        Parse the result from the langchain chain.

        :param chain_result: The result from invoking the agent chain.
                        Can be:
                        * An AgentFinish instance whose return_values can be any one of the following
                        * A dictionary whose keys might be:
                            "output" - the actual output to use
                            "messages" - effectively a chat history
                        * An AIMessage whose content is the output to use
        :param exception: Any exception that happened along the way
        :param backtrace: Any backtrace to the exception that happened along the way
        :return: A string value to return as the result of the run.
        """

        # Initialize our output.
        # The value here might morph a bit between types, but when we return
        # something we expect it to be a string.
        output: Union[str, List[Dict[str, Any]]] = None

        if chain_result is None and exception is not None:
            # We got an exception instead of a proper result. Say so.
            output = f"Agent stopped due to exception {exception}"
        else:
            # Set some stuff up for later
            backtrace = None
            ai_message: AIMessage = None

            # Handle the AgentFinish case.
            # The return_values from there contain our output whether in string or dict form.
            # ??? From what path does this come?
            if isinstance(chain_result, AgentFinish):
                chain_result = chain_result.return_values

            if isinstance(chain_result, Dict):
                # Normal return value from a chain is a dict.
                # The dict in question usually has chat history in a messages field.
                # We want the last AIMessage from that chat history.
                messages: List[BaseMessage] = chain_result.get("messages", [])
                for message in reversed(messages):
                    if isinstance(message, AIMessage):
                        ai_message = message
                        break

                if ai_message is None:
                    # We didn't find an AIMessage, so look for straight-up output key
                    output = chain_result.get("output")

            elif isinstance(chain_result, AIMessage):
                # Sometimes we get an AIMessage from a tool call.
                ai_message = chain_result

            if ai_message is not None:
                # We generally want the content of any single AIMessage we found from above
                output = ai_message.content

        # In general, output is a string. but output from Anthropic can either be
        # a single string or a list of content blocks.
        # If it is a list, "text" is a key of a dictionary which is the first element of
        # the list. For more details: https://python.langchain.com/docs/integrations/chat/anthropic/#content-blocks
        if isinstance(output, list):
            output = output[0].get("text", "")

        # See if we had some kind of error and format accordingly, if asked for.
        output = self.error_detector.handle_error(output, backtrace)
        return output
