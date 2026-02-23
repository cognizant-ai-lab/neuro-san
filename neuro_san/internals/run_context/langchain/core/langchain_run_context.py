
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

import json
import uuid

from copy import copy
from logging import Logger
from logging import getLogger

from pydantic_core import ValidationError

from langchain.agents.factory import create_agent
from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.system import SystemMessage
from langchain_core.prompts.chat import ChatPromptTemplate
from langchain_core.runnables.base import Runnable
from langchain_core.runnables.passthrough import RunnablePassthrough
from langchain_core.tools.base import BaseTool

from leaf_common.config.resolver_util import ResolverUtil

from neuro_san.internals.errors.error_detector import ErrorDetector
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.journals.intercepting_journal import InterceptingJournal
from neuro_san.internals.journals.originating_journal import OriginatingJournal
from neuro_san.internals.messages.origination import Origination
from neuro_san.internals.messages.agent_tool_result_message import AgentToolResultMessage
from neuro_san.internals.messages.base_message_dictionary_converter import BaseMessageDictionaryConverter
from neuro_san.internals.run_context.interfaces.run import Run
from neuro_san.internals.run_context.interfaces.run_context import RunContext
from neuro_san.internals.run_context.interfaces.tool_caller import ToolCaller
from neuro_san.internals.run_context.langchain.core.base_tool_factory import BaseToolFactory
from neuro_san.internals.run_context.langchain.core.langchain_run import LangChainRun
from neuro_san.internals.run_context.langchain.core.run_context_runnable import RunContextRunnable
from neuro_san.internals.run_context.langchain.llms.langchain_llm_resources import LangChainLlmResources


MINUTES: float = 60.0

# Lazily import specific errors from llm providers
API_ERROR_TYPES: Tuple[Type[Any], ...] = ResolverUtil.create_type_tuple([
                                            "openai.APIError",
                                            "anthropic.APIError",
                                            "langchain_google_genai.chat_models.ChatGoogleGenerativeAIError",
                                         ])


# pylint: disable=too-many-instance-attributes,too-many-public-methods
class LangChainRunContext(RunContext):
    """
    LangChain implementation on RunContext interface supporting high-level LLM usage
    This ends up being useful:
        https://python.langchain.com/docs/modules/tools/tools_as_openai_functions/
    Note that "tools" can be just a list of OpenAI functions JSON.
    """

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def __init__(self, llm_config: Dict[str, Any],
                 parent_run_context: RunContext,
                 tool_caller: ToolCaller,
                 invocation_context: InvocationContext,
                 chat_context: Dict[str, Any]):
        """
        Constructor

        :param llm_config: The default llm_config to use as an overlay
                            for the tool-specific llm_config
        :param parent_run_context: The parent RunContext that is calling this one. Can be None.
        :param tool_caller: The tool caller to use
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param chat_context: A ChatContext dictionary that contains all the state necessary
                to carry on a previous conversation, possibly from a different server.
        """
        self.chat_history: List[BaseMessage] = []
        self.journal: Journal = None
        self.interceptor: InterceptingJournal = None
        self.llm_resources: LangChainLlmResources = None
        self.agent_chain: Runnable = None

        # This might get modified in create_resources() (for now)
        self.llm_config: Dict[str, Any] = llm_config
        self.run_id_base: str = str(uuid.uuid4())

        self.tools: List[BaseTool] = []
        self.error_detector: ErrorDetector = None
        self.recent_human_message: HumanMessage = None
        self.tool_caller: ToolCaller = tool_caller
        self.invocation_context: InvocationContext = invocation_context
        self.chat_context: Dict[str, Any] = chat_context
        self.origin: List[Dict[str, Any]] = []
        # Have we already created resources for this RunContext:
        self.resources_created: bool = False
        # Default logger
        self.logger: Logger = getLogger(self.__class__.__name__)

        parent_origin: List[Dict[str, Any]] = []
        if parent_run_context is not None:

            # Get other stuff from parent if not specified
            if self.invocation_context is None:
                self.invocation_context = parent_run_context.get_invocation_context()
            if self.chat_context is None:
                self.chat_context = parent_run_context.get_chat_context()
            parent_origin = parent_run_context.get_origin()

            # Initialize the origin.
            agent_name: str = tool_caller.get_name()
            origination: Origination = self.invocation_context.get_origination()
            self.origin = origination.add_spec_name_to_origin(parent_origin, agent_name)

        self.update_from_chat_context(self.chat_context)

        # Set up so local logging gives origin info.
        if self.origin is not None and len(self.origin) > 0:
            full_name: str = Origination.get_full_name_from_origin(self.origin)
            self.logger = getLogger(full_name)

        if self.invocation_context is not None:
            # Sets up self.journal
            self.update_invocation_context(self.invocation_context)

    async def create_resources(self, agent_name: str,
                               instructions: str,
                               assignments: str,
                               tool_names: List[str] = None):
        """
        Creates resources for later use within the RunContext instance.
        Results are stored as a member in this instance for future use.

        Note that even though this method is labeled as async, we don't
        really do any async method calls in here for this implementation.

        :param agent_name: String name of the agent
        :param instructions: string instructions that are used
                    to create the agent
        :param assignments: string assignments of function parameters that are used as input
        :param tool_names: The list of registered tool names to use.
                    Default is None implying no tool is to be called.
        """
        # DEF - Remove the arg if possible
        if self.resources_created:
            # Don't create RunContext resources twice -
            # we could possibly leak some run-time resources.
            return

        _ = agent_name

        full_name: str = Origination.get_full_name_from_origin(self.origin)
        agent_spec: Dict[str, Any] = self.tool_caller.get_agent_tool_spec()

        # Now that we have a name, we can create an ErrorDetector for the output.
        self.error_detector = ErrorDetector(full_name,
                                            error_formatter_name=agent_spec.get("error_formatter"),
                                            system_error_fragments=["Agent stopped"],
                                            agent_error_fragments=agent_spec.get("error_fragments"))

        if tool_names is not None:
            factory = BaseToolFactory(self.tool_caller, self.invocation_context, self.journal)
            for tool_name in tool_names:
                tool: Union[BaseTool | List[BaseTool]] = await factory.create_base_tool(tool_name)
                if tool is not None:
                    if isinstance(tool, List):
                        self.tools.extend(tool)
                    else:
                        self.tools.append(tool)

        prompt_template: ChatPromptTemplate = await self.create_prompt_template(instructions)

        self.agent_chain = self.create_agent_with_fallbacks(prompt_template)
        self.resources_created = True

    def create_agent_with_fallbacks(self, prompt_template: ChatPromptTemplate) -> Runnable:
        """
        Creates an agent with potential fallback llms to use.
        :param prompt_template: The ChatPromptTemplate to use for the agent
        :return: An Agent (Runnable)
        """
        # Initialize our return value
        agent: Runnable = None

        # Get the factory we will use
        llm_factory: ContextTypeLlmFactory = self.invocation_context.get_llm_factory()

        # Prepare a list of fallbacks.  By default, the llm_config itself is a single-entry fallback list.
        fallbacks: List[Dict[str, Any]] = [self.llm_config]
        fallbacks = self.llm_config.get("fallbacks", fallbacks)

        # Initialize a list of chain fallbacks. This may or may not get filled.
        chain_fallbacks: List[Runnable] = []

        # Go through the list of fallbacks in the config.
        for index, fallback in enumerate(fallbacks):

            # Create a model we might use.
            one_llm_resources: LangChainLlmResources = llm_factory.create_llm(fallback)
            one_agent: Runnable = self.create_agent(prompt_template, one_llm_resources.get_model())

            if index == 0:
                # The first agent is the one we want to be our main guy.
                agent = one_agent
                # For now. Could be problems with different providers w/ token counting.
                self.llm_resources = one_llm_resources
            else:
                # Anything later than the first guy is considered a fallback. Add it to the list.
                chain_fallbacks.append(one_agent)

        if len(chain_fallbacks) > 0:
            # Set up fallbacks.
            # See https://python.langchain.com/docs/how_to/tools_error/#tryexcept-tool-call
            agent = agent.with_fallbacks(chain_fallbacks)

        return agent

    def create_agent(self, prompt_template: ChatPromptTemplate, llm: BaseLanguageModel) -> Runnable:
        """
        Creates an agent.
        :param prompt_template: The ChatPromptTemplate to use for the agent
        :param llm: The BaseLanguageModel to use for the agent
        :return: An Agent (Runnable)
        """
        # Initialize our return value
        agent: Runnable = None

        # Determine how complex the meat of our agent chain will be
        meat: Runnable = llm
        if len(self.tools) > 0:
            meat = create_agent(model=llm, tools=self.tools)

        # This uses LangChain Expression Language (LCEL), which enables a functional, pipeline-style composition
        # using "|". Here, we pass `agent_scratchpad` in the input message, but since we don't explicitly assign it
        # to `intermediate_steps` (as done in the old `create_tool_calling_agent`), it remains unused by the prompt.
        #
        # In contrast, the old `create_tool_calling_agent` can be written in LCEL as
        # RunnablePassthrough | prompt | llm_with_tools | ToolsAgentOutputParser
        # where RunnablePassthrough `agent scratchpad` convert (AgentAction, tool output) tuples into ToolMessages.
        #
        # By skipping this step, our agent functions as a pure LLM-driven system with a defined role,
        # without tool invocation logic influencing its decision-making.

        agent = prompt_template | meat

        return agent

    async def create_prompt_template(self, instructions: str) -> ChatPromptTemplate:
        """
        Creates a ChatPromptTemplate given the generic instructions
        """
        # Assemble the prompt message list
        message_list: List[Tuple[str, str]] = []

        system_message = SystemMessage(instructions)
        if not self.chat_history:
            await self.journal.write_message(system_message)
        message_list.append(("system", instructions))

        # Fill out the rest of the prompt per the docs for create_tooling_agent()
        # Note we are not write_message()-ing the chat history because that is redundant
        # Unclear if we should somehow/someplace write_message() the agent_scratchpad at all.
        message_list.extend([
            ("placeholder", "{chat_history}"),
            ("human", "{input}"),
        ])

        prompt: ChatPromptTemplate = ChatPromptTemplate.from_messages(message_list)

        return prompt

    async def submit_message(self, user_message: str) -> Run:
        """
        Submits a message to the model used by this instance.

        Note that even though this method is labeled as async, we don't
        really do any async method calls in here for this implementation.

        :param user_message: The message to submit
        :return: The run which is processing the agent's message
        """
        # Contruct a human message out of the text of the user message
        # Don't add this to the chat history yet.
        try:
            self.recent_human_message = HumanMessage(user_message)
        except ValidationError as exception:
            full_name: str = Origination.get_full_name_from_origin(self.origin)
            message = f"ValidationError in {full_name} with message: {user_message}"
            raise ValueError(message) from exception

        # Create a run to return
        run = LangChainRun(self.run_id_base, self.chat_history)
        return run

    async def wait_on_run(self, run: Run, journal: Journal = None) -> Run:
        """
        Loops on the given run's status for model invokation.

        This truly is an asynchronous method.

        :param run: The run to wait on
        :param journal: The Journal which captures the "thinking" messages.
        :return: An potentially updated run
        """
        _ = run, journal

        # Chat history is updated in write_message() below, so to save on
        # some tokens, make a shallow copy of it here as we send it to the LLM
        previous_chat_history: List[BaseMessage] = copy(self.chat_history)

        inputs = {
            "chat_history": previous_chat_history,
            "input": self.recent_human_message.content
        }

        run: Run = LangChainRun(self.run_id_base, self.chat_history)
        session_id: str = run.get_id()

        runnable = RunContextRunnable(agent_chain=self.agent_chain,
                                      primary_llm=self.llm_resources.get_model(),
                                      invocation_context=self.invocation_context,
                                      journal=self.journal,
                                      interceptor=self.interceptor,
                                      origin=self.origin,
                                      tool_caller=self.tool_caller,
                                      error_detector=self.error_detector,
                                      session_id=session_id)
        runnable_config: Dict[str, Any] = runnable.prepare_runnable_config(session_id=session_id, use_run_name=True)

        # This needs to be run as a chain otherwise LangSmith will pick up two
        # trace names for the same request.
        chain: Runnable = RunnablePassthrough() | runnable

        await chain.ainvoke(input=inputs, config=runnable_config)

        return run

    async def get_response(self) -> List[BaseMessage]:
        """
        :return: The list of messages from the instance's thread.
        """
        # Not sure if this is the right thing, as this will be langchain-y stuff.
        return self.chat_history

    async def submit_tool_outputs(self, run: Run, tool_outputs: List[Dict[str, Any]]) -> Run:
        """
        :param run: The Run handling the execution of the agent
        :param tool_outputs: The tool outputs to submit
                The component dictionaries can have the following keys:
                    "origin"        A List of origin dictionaries indicating the origin of the run.
                    "output"        A string representing the output of the tool call
                    "sly_data"      Optional sly_data dictionary that might have returned from an external tool.
                    "tool_call_id"  The string id of the tool_call being executed
        :return: A potentially updated run handle
        """
        tool_message: BaseMessage = None
        if tool_outputs is not None and len(tool_outputs) > 0:
            for tool_output in tool_outputs:
                tool_message = self.parse_tool_output(tool_output)
                if tool_message is not None:
                    # Write the tool message to the journal.
                    # Chat history should only contain user and AI messages.
                    # It will not be updated in the write_message() call below.
                    await self.journal.write_message(tool_message)

        # Create a run to return
        run = LangChainRun(self.run_id_base, self.chat_history, tool_message=tool_message)

        return run

    def parse_tool_output(self, tool_output: Dict[str, Any]) -> BaseMessage:
        """
        Parse a single tool_output dictionary for its results
        :return: A message representing the output from the tool.
        """

        # Get a Message for each output and add to the chat history.
        # Assuming dictionary
        tool_chat_list_string = tool_output.get("output", None)
        if tool_chat_list_string is None:
            # Dunno what to do with None tool output
            return None
        if isinstance(tool_chat_list_string, tuple):
            # Sometimes output comes back as a tuple.
            # The output we want is the first element of the tuple.
            tool_chat_list_string = tool_chat_list_string[0]

        tool_message: BaseMessage = None
        if isinstance(tool_chat_list_string, str):
            # Sometimes output comes back as a list.
            # The output we want is the first element of the list.
            tool_message = self.parse_tool_chat_list_string(tool_chat_list_string, tool_output.get("origin"))

        elif isinstance(tool_chat_list_string, BaseMessage):
            tool_message = AgentToolResultMessage(content=tool_chat_list_string.content,
                                                  tool_result_origin=tool_output.get("origin"))

        elif isinstance(tool_chat_list_string, list) and isinstance(tool_chat_list_string[-1], BaseMessage):
            # Always take the last element of the list as the answer to the tool output
            last_message: BaseMessage = tool_chat_list_string[-1]
            tool_message = AgentToolResultMessage(content=last_message.content,
                                                  tool_result_origin=tool_output.get("origin"))
        else:
            self.logger.warning("Dunno what to do with %s tool output %s",
                                str(tool_chat_list_string.__class__.__name__),
                                str(tool_chat_list_string))
            return None

        # Integrate any sly data
        tool_sly_data: Dict[str, Any] = tool_output.get("sly_data")
        if tool_sly_data and tool_sly_data != self.tool_caller.get_sly_data():
            # We have sly data from the tool output that is not the same as our own
            # and it has data in it.  Integrate that.
            # It's possible we might need to run a SlyDataRedactor against from_download.sly_data on this.
            self.tool_caller.get_sly_data().update(tool_sly_data)

        return tool_message

    def parse_tool_chat_list_string(self, tool_chat_list_string: str, origin: str) -> BaseMessage:
        """
        Parse a tool output string into a list of messages
        :param tool_chat_list_string: The string to parse
        :param origin: The origin of the tool
        :return: A list of messages representing the output from the tool.
        """

        # Remove bracketing quotes from within the string
        while (tool_chat_list_string[0] == '"' and tool_chat_list_string[-1] == '"') or \
              (tool_chat_list_string[0] == "'" and tool_chat_list_string[-1] == "'"):
            tool_chat_list_string = tool_chat_list_string[1:-1]

        # Remove escaping
        tool_chat_list_string = tool_chat_list_string.replace('\\"', '"')
        # Put back some escaping of double quotes in messages that are not json.
        # We have to do this because gpt-4o seems to not like json braces in its
        # input, but now we have to deal with the consequences in the output.
        # See ArgumentAssigner.get_args_value_as_string().
        tool_chat_list_string = tool_chat_list_string.replace('\\"', '\\\\\"')

        # Decode the JSON in that string now.
        tool_chat_list: List[Dict[str, Any]] = None
        try:
            tool_chat_list = json.loads(tool_chat_list_string)
        except json.decoder.JSONDecodeError as exception:
            self.logger.error("Exception: %s parsing %s", str(exception), str(tool_chat_list_string))
            raise exception

        # The tool_output seems to contain the entire chat history of
        # the call to the tool. For now just take the last one as the answer.
        tool_result_dict = tool_chat_list[-1]

        # Turn that guy into a BaseMessage
        # You might expect that this should be a ToolMessage, but making that
        # kind of conversion at this point runs into problems with OpenAI models
        # that process them.  So, to make things continue to work, report the
        # content as an AI message - as if the bot came up with the answer itself.
        tool_message = AgentToolResultMessage(content=tool_result_dict.get("content"),
                                              tool_result_origin=origin)

        return tool_message

    async def delete_resources(self, parent_run_context: RunContext = None):
        """
        Cleans up the service-side resources associated with this instance
        :param parent_run_context: A parent RunContext perhaps the same instance,
                        but perhaps not.  Default is None
        """

        # Release model related resources:
        if self.llm_resources:
            await self.llm_resources.delete_resources()

        self.tools = []
        self.chat_history = []
        self.agent_chain = None
        self.recent_human_message = None
        self.llm_resources = None
        self.journal = None
        self.interceptor = None

    def get_agent_tool_spec(self) -> Dict[str, Any]:
        """
        :return: the dictionary describing the data-driven agent
        """
        if self.tool_caller is None:
            return None

        return self.tool_caller.get_agent_tool_spec()

    def get_invocation_context(self) -> InvocationContext:
        """
        :return: The InvocationContext policy container that pertains to the invocation
                    of the agent.
        """
        return self.invocation_context

    def get_chat_context(self) -> Dict[str, Any]:
        """
        :return: A ChatContext dictionary that contains all the state necessary
                to carry on a previous conversation, possibly from a different server.
                Can be None when a new conversation has been started.
        """
        return self.chat_context

    def get_origin(self) -> List[Dict[str, Any]]:
        """
        :return: A List of origin dictionaries indicating the origin of the run.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
        """
        return self.origin

    def update_invocation_context(self, invocation_context: InvocationContext):
        """
        Update internal state based on the InvocationContext instance passed in.
        :param invocation_context: The context policy container that pertains to the invocation
        """
        old_interceptor: InterceptingJournal = self.interceptor
        self.invocation_context = invocation_context

        # Make a nested chain where each journal is wrapped by the next
        base_journal: Journal = self.invocation_context.get_journal()
        self.interceptor = InterceptingJournal(wrapped_journal=base_journal, origin=self.origin)

        # The SystemMessage has already been written to the journal
        # need to transfer it over when this shift happens.
        if old_interceptor is not None:
            for message in old_interceptor.get_messages():
                self.interceptor.write_unwrapped_message(message, self.origin)
        self.journal = OriginatingJournal(self.interceptor, self.origin, self.chat_history)

    def update_from_chat_context(self, chat_context: Dict[str, Any]):
        """
        :param chat_context: A ChatContext dictionary that contains all the state necessary
                to carry on a previous conversation, possibly from a different server.
        """
        self.chat_context = chat_context

        if self.chat_context is None:
            return

        # See if our origin appears in the chat histories.
        # If so, get ours from there.
        empty: List[Any] = []
        chat_histories: List[Dict[str, Any]] = self.chat_context.get("chat_histories", empty)
        our_origin_str: str = Origination.get_full_name_from_origin(self.origin)
        for one_chat_history in chat_histories:

            # See if the origin matches our own
            test_origin: List[Dict[str, Any]] = one_chat_history.get("origin", empty)
            test_origin_str: str = Origination.get_full_name_from_origin(test_origin)
            if test_origin_str != our_origin_str:
                continue

            one_messages: List[Dict[str, Any]] = one_chat_history.get("messages", empty)
            if not one_messages:
                # Empty list - Nothing to convert. Use default empty list.
                break

            converter = BaseMessageDictionaryConverter()
            self.chat_history = []
            for chat_message in one_messages:
                base_message: BaseMessage = converter.from_dict(chat_message)
                if base_message is not None:
                    self.chat_history.append(base_message)

            # Nothing left to search for
            break

    def get_journal(self) -> Journal:
        """
        :return: The Journal associated with the instance
        """
        return self.journal
