
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
# Needed for method referencing different instance of the same class
# See https://stackoverflow.com/questions/33533148/how-do-i-type-hint-a-method-with-the-type-of-the-enclosing-class
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List

import asyncio
import time

from leaf_common.config.dictionary_overlay import DictionaryOverlay

from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.role_utils import RoleUtils
from neuro_san.internals.run_context.interfaces.agent_network_inspector import AgentNetworkInspector
from neuro_san.internals.run_context.interfaces.run import Run
from neuro_san.internals.run_context.interfaces.run_context import RunContext
from neuro_san.internals.run_context.interfaces.tool_caller import ToolCaller
from neuro_san.internals.run_context.openai.openai_client import OpenAIClient
from neuro_san.internals.run_context.openai.openai_run import OpenAIRun


# pylint: disable=too-many-instance-attributes
class OpenAIRunContext(RunContext):
    """
    RunContext implementation supporting the context/lifetime in
    which OpenAI calls are made.
    """

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def __init__(self, llm_config: Dict[str, Any], parent_run_context: RunContext,
                 tool_caller: ToolCaller, invocation_context: InvocationContext,
                 chat_context: Dict[str, Any]):
        """
        Constructor

        :param llm_config: The default llm_config to use as an overlay
                            for the tool-specific llm_config
        :param parent_run_context: The parent RunContext (if any) to pass
                             down its resources to a new RunContext created by
                             this call.
        :param tool_caller: The tool caller to use
        :param invocation_context: The InvocationContext policy container that pertains to the invocation
                    of the agent.
        :param chat_context: A ChatContext dictionary that contains all the state necessary
                to carry on a previous conversation, possibly from a different server.
                Can be None when a new conversation has been started.
        """

        # This might get modified in create_resources() (for now)
        self.llm_config: Dict[str, Any] = llm_config
        self.tool_caller: ToolCaller = tool_caller

        # Set up the connection to OpenAI
        self.openai_client: OpenAIClient = None
        if parent_run_context is None:
            self.openai_client = OpenAIClient(asynchronous=True)
        elif isinstance(parent_run_context, OpenAIRunContext):
            # Use the same client as the parent
            self.openai_client = parent_run_context.openai_client
        else:
            raise ValueError("parent_run_context must be OpenAIRunContext")

        # Other state initialized later
        self.thread_id: str = None
        self.assistant_id: str = None
        self.invocation_context: InvocationContext = invocation_context
        self.chat_context: Dict[str, Any] = chat_context
        self.journal: Journal = self.invocation_context.get_journal()

    # pylint: disable=too-many-locals
    async def create_resources(self, agent_name: str,
                               instructions: str,
                               assignments: str,
                               tool_names: List[str] = None):
        """
        Creates the thread resource on the OpenAI service side.
        The result is stored as a member in this instance for future use.
        :param agent_name: String name of the assistant that can show up in the
                    OpenAI web API.
        :param instructions: string instructions that are used to create the OpenAI assistant
        :param assignments: string assignments of function parameters that are used as input
        :param tool_names: The list of registered tool names to use.
                    Default is None implying no tool is to be called.
                    Note that this implementation can only handle the 1st tool in the list
        """
        # Create the config we will use from here on out
        overlayer = DictionaryOverlay()
        tool_llm_config: Dict[str, Any] = {}

        tool_name: str = None
        if tool_names is not None and len(tool_names) > 0:
            # We can only use the first tool name in this implementation for now
            tool_name = tool_names[0]

        inspector: AgentNetworkInspector = self.tool_caller.get_inspector()
        tool_spec: Dict[str, Any] = inspector.get_agent_tool_spec(tool_name)

        if tool_spec is not None:
            tool_llm_config = tool_spec.get("llm_config")
        self.llm_config = overlayer.overlay(self.llm_config, tool_llm_config)

        model_name: str = self.llm_config.get("model_name")

        use_instructions: str = instructions
        if assignments is not None:
            use_instructions = use_instructions + assignments

        # Create the assistant
        assistant = await self.openai_client.create_assistant(
            name=agent_name,
            instructions=use_instructions,
            model=model_name,
        )
        self.assistant_id = assistant.id

        # Create the thread
        thread = await self.openai_client.create_thread()
        self.thread_id = thread.id

        use_tools = [
            {"type": "code_interpreter"}
        ]
        function_json: Dict[str, Any] = None
        if tool_spec is not None:
            function_json = tool_spec.get("function")
        if function_json is not None:
            use_tools.append({
                "type": "function",
                "function": function_json
            })
        assistant = await self.openai_client.update_assistant(
            self.assistant_id,
            tools=use_tools
        )

    async def submit_message(self, user_message: str) -> Run:
        """
        Submits a message to create an OpenAI run.
        :param user_message: The message to submit
        :return: The OpenAI run which is processing the assistant's message
        """

        await self.openai_client.create_message(
            thread_id=self.thread_id, role="user", content=user_message
        )
        openai_run = await self.openai_client.create_run(
            thread_id=self.thread_id,
            assistant_id=self.assistant_id,
        )
        run = OpenAIRun(openai_run)
        return run

    async def wait_on_run(self, run: Run, journal: Journal = None) -> Run:
        """
        Loops on the given run's status for OpenAI service-side processing
        to be done.
        :param run: The OpenAI run on their servers
        :param journal: The Journal which captures the "thinking" messages.
        :return: An potentially updated Run
        """
        messages = await self.openai_client.list_messages(thread_id=self.thread_id)
        while run.is_running():
            openai_run = await self.openai_client.retrieve(
                thread_id=self.thread_id,
                run_id=run.get_id()
            )

            sleep_seconds = 0.5
            if self.openai_client.is_async():
                await asyncio.sleep(sleep_seconds)
            else:
                time.sleep(sleep_seconds)

            latest_messages = await self.openai_client.list_messages(thread_id=self.thread_id)

            last_message_with_content = self.get_last_message_with_content(messages)
            latest_message_with_content = self.get_last_message_with_content(latest_messages)
            if (latest_messages and messages and latest_message_with_content and
                (len(latest_messages) > len(messages) or
                    (len(latest_message_with_content.content[0].text.value) >
                        len(last_message_with_content.content[0].text.value)))):
                # number_of_new_messages = len(latest_messages) - len(messages)
                # new_messages = latest_messages[-number_of_new_messages:]
                # Write to the journal
                # if journal is not None:
                messages = latest_messages

            run = OpenAIRun(openai_run)

        return run

    async def get_response(self) -> List[Any]:
        """
        :return: The list of OpenAI messages from the instance's thread.
        """
        return await self.openai_client.list_messages(thread_id=self.thread_id)

    async def submit_tool_outputs(self, run: Run, tool_outputs: List[Any]) -> Run:
        """
        :param run: The OpenAI run handling the execution of the assistant
        :param tool_outputs: The tool outputs to submit
        :return: A potentially updated OpenAI Run handle
        """
        openai_run = await self.openai_client.submit_tool_outputs(
            thread_id=self.thread_id,
            run_id=run.get_id(),
            tool_outputs=tool_outputs
        )
        run = OpenAIRun(openai_run)
        return run

    async def delete_resources(self, parent_run_context: RunContext = None):
        """
        Cleans up the OpenAI service-side resources associated with this instance
        :param parent_run_context: A parent RunContext perhaps the same instance,
                        but perhaps not.  Default is None
        """
        if parent_run_context is None:
            # No parent run context. Always try to delete the resources
            if self.assistant_id is not None:
                await self.openai_client.delete_assistant(self.assistant_id)
                self.assistant_id = None
            if self.thread_id is not None:
                await self.openai_client.delete_thread(self.thread_id)
                self.thread_id = None
        else:
            # Do not delete the resources if they are the same as the parent run context
            if self.assistant_id is not None and self.assistant_id != parent_run_context.assistant_id:
                await self.openai_client.delete_assistant(self.assistant_id)
                self.assistant_id = None
            if self.thread_id is not None and self.thread_id != parent_run_context.thread_id:
                await self.openai_client.delete_thread(self.thread_id)
                self.thread_id = None

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
        return []

    def update_invocation_context(self, invocation_context: InvocationContext):
        """
        Update internal state based on the InvocationContext instance passed in.
        :param invocation_context: The context policy container that pertains to the invocation
        """
        self.invocation_context = invocation_context

    def get_journal(self) -> Journal:
        """
        :return: The Journal associated with the instance
        """
        return self.journal

    @staticmethod
    def get_last_message_with_content(messages: List[Any]) -> object:
        """
        Sometimes just indexing a message list by [-1]
        gives you a message that does not actually have any content.
        This method gives you the last messages that does have content.

        :param messages: input list of OpenAI messages
        :return: An applicalble OpenAI message (or None if no message is applicable)
        """

        messages_list = list(messages)

        for m in reversed(messages_list):
            if any(RoleUtils.get_content(m)):
                return m

        return None
