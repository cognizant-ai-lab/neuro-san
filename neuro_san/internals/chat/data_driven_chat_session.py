
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
from typing import Iterator
from typing import List
from typing import Tuple
from typing import Type
from typing import Union

import copy
import traceback

from logging import getLogger
from logging import Logger
from inspect import iscoroutinefunction

from langchain_core.messages.base import BaseMessage

from leaf_common.config.resolver_util import ResolverUtil

from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.chat.chat_history_message_processor import ChatHistoryMessageProcessor
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.graph.registry.agent_tool_registry import AgentToolRegistry
from neuro_san.internals.graph.activations.sly_data_redactor import SlyDataRedactor
from neuro_san.internals.interfaces.context_type_tracing_context_factory import ContextTypeTracingContextFactory
from neuro_san.internals.interfaces.front_man import FrontMan
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.interfaces.run_target import RunTarget
from neuro_san.internals.journals.intercepting_journal import InterceptingJournal
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.agent_framework_message import AgentFrameworkMessage
from neuro_san.internals.messages.base_message_dictionary_converter import BaseMessageDictionaryConverter
from neuro_san.internals.run_context.factory.run_context_factory import RunContextFactory
from neuro_san.internals.run_context.factory.master_tracing_context_factory import MasterTracingContextFactory
from neuro_san.internals.run_context.interfaces.run_context import RunContext
from neuro_san.message_processing.message_processor import MessageProcessor
from neuro_san.message_processing.answer_message_processor import AnswerMessageProcessor
from neuro_san.message_processing.structure_message_processor import StructureMessageProcessor

# Lazily import specific errors from llm providers
PATIENCE_ERRORS: Tuple[Type[Any], ...] = ResolverUtil.create_type_tuple([
                                            "openai.BadRequestError",
                                         ])


# pylint: disable=too-many-instance-attributes
class DataDrivenChatSession(RunTarget):
    """
    ChatSession implementation that consolidates policy
    in using data-driven agent tool graphs.
    """

    def __init__(self, agent_network: AgentNetwork):
        """
        Constructor

        :param agent_network: The AgentNetwork to use.
        """
        # We make a copy of the AgentNetwork at this level to allow for interactions
        # within this scope to modify the network topology.
        agent_network_copy: AgentNetwork = copy.deepcopy(agent_network)
        self.registry: AgentToolRegistry = AgentToolRegistry(agent_network_copy)

        self.front_man: FrontMan = None
        self.sly_data: Dict[str, Any] = {}

        # This is the context policy container that pertains to the invocation
        # of run_it()
        self.invocation_context: InvocationContext = None
        self.interceptor: InterceptingJournal = None
        self.original_input_message: AgentFrameworkMessage = None

    async def set_up(self, invocation_context: InvocationContext,
                     sly_data: Dict[str, Any] = None,
                     chat_context: Dict[str, Any] = None):
        """
        Resets or sets the instance up for the first time.
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be None.
        :param chat_context: A ChatContext dictionary that contains all the state necessary
                to carry on a previous conversation, possibly from a different server.
        """

        # Reset any sly data
        # This ends up being the one reference to the sly_data that gets passed around
        # to the graph components. Updating this updates everyone else.
        self.sly_data = {}

        # Reset what we might have created before.
        await self.delete_resources()

        # Update sly data (if any) with what was passed in.
        # Note that since this instance is the owner of the sly_data,
        # any update here should get transmitted to all the other graph components
        # because it is expected they share the reference and only interact with it
        # in a read-only fashion.
        if sly_data is not None:
            self.sly_data.update(sly_data)

        # Update sly data with metadata from the request headers so this information
        # can be made available in CodedTools, privately, without any leakage to LLMs.
        # Only add this if it doesn't already exist w/rt what the user gave us.
        if self.sly_data.get("request_metadata") is None:
            # Make a deep copy so the server's idea of the original metadata doesn't get modified
            # should any CodedTool somehow get the idea to modify it.
            self.sly_data["request_metadata"] = copy.deepcopy(invocation_context.get_metadata())

        run_context: RunContext = RunContextFactory.create_run_context(None, None,
                                                                       invocation_context=invocation_context,
                                                                       chat_context=chat_context)

        self.front_man = self.registry.create_front_man(self.sly_data, run_context)

        await self.front_man.create_any_resources()

    async def chat(self, user_input: str,
                   invocation_context: InvocationContext,
                   sly_data: Dict[str, Any] = None) -> Iterator[Dict[str, Any]]:
        """
        Performs a portion of the streaming_chat() responsibilities

        :param user_input: A string with the user's input
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be None.
        :return: An Iterator over dictionary representation of chat messages.
                The keys/values/structure of these chat message dictionaries will reflect
                instances of ChatMessage from chat.proto.

                Note that Iterators themselves are *not* simply lists. They are a Python
                construct intended for use in a for-loop that is allowed to come up with
                its content dynamically.  For our purposes, when an initiator of chat()
                gets a handle to this Iterator, they can begin looping/waiting on its contents
                without the content itself having been created yet.  This is a building
                block of streaming results even though direct callers may not actually
                be streaming.
        """
        if self.front_man is None:
            await self.set_up(invocation_context, sly_data)
        else:
            self.front_man.update_invocation_context(invocation_context)

        try:
            # DEF - drill further down for iterator from here to enable getting
            #       messages from downstream agents.
            raw_messages: List[BaseMessage] = await self.front_man.submit_message(user_input)

        except PATIENCE_ERRORS:
            # This can happen if the user is trying to send a new message
            # while it is still working on a previous message that has not
            # yet returned.
            raw_messages: List[BaseMessage] = [
                AgentFrameworkMessage(content="Patience, please. I'm working on it.")
            ]

            logger: Logger = getLogger(self.__class__.__name__)
            logger.error(traceback.format_exc())

        converter = BaseMessageDictionaryConverter(origin=self.front_man.get_origin())
        chat_messages: List[Dict[str, Any]] = []
        for raw_message in raw_messages:
            chat_message: Dict[str, Any] = converter.to_dict(raw_message)
            chat_messages.append(chat_message)

        return iter(chat_messages)

    # pylint: disable=too-many-locals
    async def streaming_chat(self, user_input: str,
                             invocation_context: InvocationContext,
                             sly_data: Dict[str, Any] = None,
                             chat_context: Dict[str, Any] = None):
        """
        Main streaming entry-point method for accepting new user input
        invoked by DirectAgentSession and its friends.

        :param user_input: A string with the user's input
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be None.
        :param chat_context: A ChatContext dictionary that contains all the state necessary
                to carry on a previous conversation, possibly from a different server.
        :return: Nothing.  Response values are put on a queue whose consumtion is
                managed by the Iterator aspect of AsyncCollatingQueue on the InvocationContext.
        """
        # Set up some member variable state so that run_it() can use it
        self.invocation_context = invocation_context
        journal: Journal = self.invocation_context.get_journal()
        self.interceptor = InterceptingJournal(journal, origin=None)

        # Set up an input message that will show up in an Observability/tracing app
        # We keep this guy around for the duration of the chat session so that this class
        # has a pristine copy of what the inputs for use within run_it().
        self.original_input_message = AgentFrameworkMessage(content=user_input,
                                                            chat_context=chat_context,
                                                            sly_data=sly_data)
        # Make a copy of the input message for use in the tracing context
        # We can't use the same object as original_input_message because
        # the tracing infrastructure ends up transforming the message for display.
        input_message_for_show = AgentFrameworkMessage(trace_source=self.original_input_message)

        # Set up configuration for creating the tracing context.
        # These are the bare minimum required to get output and metadata correct
        # in the tracing reporting.
        config: Dict[str, Any] = {
            "interceptor": self.interceptor,
            "invocation_context": self.invocation_context
        }

        # Get a toolkit-specific implementation for creating the tracing context
        tracing_factory: ContextTypeTracingContextFactory = \
            MasterTracingContextFactory.create_tracing_context_factory()
        # For the factory args, we are our own run_target.
        tracing_context: RunTarget = tracing_factory.create_tracing_context(config, run_target=self)

        # Run the run_target that was given back by the factory.
        await tracing_context.run_it(input_message_for_show)

    async def run_it(self, inputs: AgentFrameworkMessage) -> AgentFrameworkMessage:
        """
        This method is effectively a callback which is invoked within
        the tracing context infrastructure for the toolkit/context_type.

        :param inputs: An AgentFrameworkMessage populated with the user's input.
        :return: The user input. (Outputs are handled by the tracing context infrastructure.)
        """
        # Get all our real input values from the original_input_message.
        # If we got it from the inputs arg, we'd get the for-show message
        # which has fields rearranged and even redacted.
        user_input: str = self.original_input_message.content
        sly_data: Dict[str, Any] = self.original_input_message.sly_data
        chat_context: Dict[str, Any] = self.original_input_message.chat_context

        if self.front_man is None:
            await self.set_up(self.invocation_context, sly_data, chat_context)

        # Save information about chat
        chat_messages: Iterator[Dict[str, Any]] = await self.chat(user_input, self.invocation_context, sly_data)
        message_list: List[Dict[str, Any]] = list(chat_messages)

        # Determine the chat_context to enable continuing the conversation
        return_chat_context: Dict[str, Any] = self.prepare_chat_context(message_list)

        # Get the front man spec. We will need it later for a few things.
        front_man_spec: Dict[str, Any] = self.front_man.get_agent_tool_spec()

        # Get the formats we should parse from the final answer from the config for the network.
        # As of 6/24/25, this is an unadvertised experimental feature.
        structure_formats: Union[str, List[str]] = front_man_spec.get("structure_formats")

        # Find "the answer" and have that be the content of the last message we send
        answer_processor = AnswerMessageProcessor(structure_formats=structure_formats)
        answer_processor.process_messages(message_list)
        answer: str = answer_processor.get_answer()
        if answer is None:
            # Can't have content as None or problems arise.
            answer = ""
        structure: Dict[str, Any] = answer_processor.get_structure()

        # Send back sly_data as the front-man permits
        redactor = SlyDataRedactor(front_man_spec,
                                   config_keys=["allow.to_upstream.sly_data"],
                                   allow_empty_dict=False)
        return_sly_data: Dict[str, Any] = redactor.filter_config(self.sly_data)

        # Stream over chat state as the last message
        # Use the interceptor to write the message.
        # This guy wraps the journal from the invocation context and listens to the
        # messages coming across, which allows us to report to the tracing infrastructure
        # at the end of the tracing context.
        message = AgentFrameworkMessage(content=answer, chat_context=return_chat_context,
                                        sly_data=return_sly_data, structure=structure)
        await self.interceptor.write_message(message, origin=None)

        # Put an end-marker on the queue to tell the consumer we truly are done
        # and it doesn't need to wait for any more messages.
        # The consumer await-s for queue.get()
        queue: AsyncCollatingQueue = self.invocation_context.get_queue()

        # The synchronous=True is necessary when an async HTTP request is at the get()-ing end of the queue,
        # as the journal messages come from inside a separate event loop from that request. The lock
        # taken here ends up being harmless in the synchronous request case (like for gRPC) because
        # we would only be blocking our own event loop.
        await queue.put_final_item(synchronous=True)

        # Now that we are done, tell the Reservationist that we used for this request
        # that there will be no more Reservations to corral.
        reservationist: Reservationist = self.invocation_context.get_reservationist()
        if reservationist is not None:
            await reservationist.close()

        # Close any objects on sly data that can be closed.
        await self.close_sly_data()

        # Bogus output, but need something for interface
        outputs: AgentFrameworkMessage = inputs
        return outputs

    async def delete_resources(self):
        """
        Frees up any service-side resources.
        """
        if self.front_man is not None:
            await self.front_man.delete_any_resources()
            self.front_man = None

    def prepare_chat_context(self, chat_message_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Prepare the chat context.

        :param chat_message_history: A list of ChatMessage dictionaries that
                comprise the front man's full chat history.
        :return: A ChatContext dictionary comprising the full state of play of
                the conversation such that it could be taken up on a different
                server instance
        """
        # OK if this is None
        max_message_history: int = self.front_man.get_agent_tool_spec().get("max_message_history")
        processor: MessageProcessor = ChatHistoryMessageProcessor(max_message_history)
        processor.process_messages(chat_message_history)

        chat_history: Dict[str, Any] = {
            "origin": self.front_man.get_origin(),
            "messages": processor.get_message_history()
        }

        # For now, we only send the front man's chat history, as that is the
        # state we had been preserving since the early days.  It is conceivable
        # this could expand to other agents in the hierarchy at some point.
        chat_context: Dict[str, Any] = {
            "chat_histories": [chat_history]
        }

        return chat_context

    def create_outgoing_message_processor(self) -> MessageProcessor:
        """
        :return: A MessageProcessor that filters messages outgoing to the client.
                How this works is based on settings on the front man.
                Can be None.
        """
        message_processor: MessageProcessor = None

        front_man_name: str = self.registry.find_front_man()
        front_man_spec: Dict[str, Any] = self.registry.get_agent_tool_spec(front_man_name)

        # Get the formats we should parse from the final answer from the config for the network.
        # As of 6/24/25, this is an unadvertised experimental feature.
        structure_formats: Union[str, List[str]] = front_man_spec.get("structure_formats")
        if structure_formats is None:
            return message_processor

        # Eventually this might be a CompositeMessageProcessor
        message_processor = StructureMessageProcessor(structure_formats)
        return message_processor

    async def close_sly_data(self):
        """
        Close any sly data value that can be closed.
        """
        if self.sly_data is None or len(self.sly_data) == 0:
            # Nothing to close
            return

        # Try closing anything that can be close()-d in the sly_data.
        for key, value in self.sly_data.items():
            # Note: It's possible we might want to try closing keys as well
            description: str = f"sly_data[{key}]"
            await self.close_one(value, description)

    async def close_one(self, value: Any, description: str):
        """
        Close a single object if it can be closed.
        :param value: The object to close
        :param description: Where the object to close came from
        """
        if not hasattr(value, "close"):
            # Nothing to close
            return

        close_method = getattr(value, "close")
        if not callable(close_method):
            # No method to call
            return

        # Call the close method
        try:
            if iscoroutinefunction(close_method):
                await close_method()
            else:
                close_method()

        except TypeError:
            # Not enough arguments to call close().
            logger: Logger = getLogger(self.__class__.__name__)
            logger.error("Unable to close() %s", description)
            logger.error(traceback.format_exc())
