
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
from typing import Dict
from typing import Iterator
from typing import List
from typing import Union

import copy
import logging
import traceback

from openai import BadRequestError

from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.chat.chat_history_message_processor import ChatHistoryMessageProcessor
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.graph.registry.agent_tool_registry import AgentToolRegistry
from neuro_san.internals.graph.activations.sly_data_redactor import SlyDataRedactor
from neuro_san.internals.interfaces.front_man import FrontMan
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.agent_framework_message import AgentFrameworkMessage
from neuro_san.internals.messages.base_message_dictionary_converter import BaseMessageDictionaryConverter
from neuro_san.internals.run_context.factory.run_context_factory import RunContextFactory
from neuro_san.internals.run_context.interfaces.run_context import RunContext
from neuro_san.message_processing.message_processor import MessageProcessor
from neuro_san.message_processing.answer_message_processor import AnswerMessageProcessor


# pylint: disable=too-many-instance-attributes
class DataDrivenChatSession:
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

    async def set_up(self, invocation_context: InvocationContext,
                     chat_context: Dict[str, Any] = None):
        """
        Resets or sets the instance up for the first time.
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param chat_context: A ChatContext dictionary that contains all the state necessary
                to carry on a previous conversation, possibly from a different server.
        """

        # Reset any sly data
        # This ends up being the one reference to the sly_data that gets passed around
        # to the graph components. Updating this updates everyone else.
        self.sly_data = {}

        # Reset what we might have created before.
        await self.delete_resources()

        run_context: RunContext = RunContextFactory.create_run_context(None, None,
                                                                       invocation_context=invocation_context,
                                                                       chat_context=chat_context)

        self.front_man = self.registry.create_front_man(self.sly_data, run_context)

        await self.front_man.create_any_resources()

    async def chat(self, user_input: str,
                   invocation_context: InvocationContext,
                   sly_data: Dict[str, Any] = None) -> Iterator[Dict[str, Any]]:
        """
        Main entry-point method for accepting new user input

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
            await self.set_up(invocation_context)
        else:
            self.front_man.update_invocation_context(invocation_context)

        # Update sly data, if any.
        # Note that since this instance is the owner of the sly_data,
        # any update here should get transmitted to all the other graph components
        # because it is expected they share the reference and only interact with it
        # in a read-only fashion.
        if sly_data is not None:
            self.sly_data.update(sly_data)

        try:
            # DEF - drill further down for iterator from here to enable getting
            #       messages from downstream agents.
            raw_messages: List[Any] = await self.front_man.submit_message(user_input)

        except BadRequestError:
            # This can happen if the user is trying to send a new message
            # while it is still working on a previous message that has not
            # yet returned.
            raw_messages: List[Any] = [
                AgentFrameworkMessage(content="Patience, please. I'm working on it.")
            ]

            logger = logging.getLogger(self.__class__.__name__)
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
        if self.front_man is None:
            await self.set_up(invocation_context, chat_context)

        # Save information about chat
        chat_messages: Iterator[Dict[str, Any]] = await self.chat(user_input, invocation_context, sly_data)
        message_list: List[Dict[str, Any]] = list(chat_messages)

        # Determine the chat_context to enable continuing the conversation
        return_chat_context: Dict[str, Any] = self.prepare_chat_context(message_list)

        # Get the formats we should parse from the final answer from the config for the network.
        # As of 6/24/25, this is an unadvertised experimental feature.
        parse_formats: Union[str, List[str]] = self.registry.get_config().get("parse_formats")

        # Find "the answer" and have that be the content of the last message we send
        answer_processor = AnswerMessageProcessor(parse_formats=parse_formats)
        answer_processor.process_messages(message_list)
        answer: str = answer_processor.get_answer()
        if answer is None:
            # Can't have content as None or problems arise.
            answer = ""
        structure: Dict[str, Any] = answer_processor.get_structure()

        # Send back sly_data as the front-man permits
        front_man_spec: Dict[str, Any] = self.front_man.get_agent_tool_spec()
        redactor = SlyDataRedactor(front_man_spec,
                                   config_keys=["allow.to_upstream.sly_data"],
                                   allow_empty_dict=False)
        return_sly_data: Dict[str, Any] = redactor.filter_config(self.sly_data)

        # Stream over chat state as the last message
        message = AgentFrameworkMessage(content=answer, chat_context=return_chat_context,
                                        sly_data=return_sly_data, structure=structure)
        journal: Journal = invocation_context.get_journal()
        await journal.write_message(message, origin=None)

        # Put an end-marker on the queue to tell the consumer we truly are done
        # and it doesn't need to wait for any more messages.
        # The consumer await-s for queue.get()
        queue: AsyncCollatingQueue = invocation_context.get_queue()
        await queue.put_final_item()

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
