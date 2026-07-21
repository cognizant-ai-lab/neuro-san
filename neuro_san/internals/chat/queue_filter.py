
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
from typing import Union

from copy import copy

from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.filters.message_filter import MessageFilter
from neuro_san.internals.filters.message_filter_factory import MessageFilterFactory
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.message_processing.message_processor import MessageProcessor
from neuro_san.message_processing.structure_message_processor import StructureMessageProcessor


class QueueFilter:
    """
    Filters messages from the input queue (the one from the MessageJournal)
    to be sure they are suitable to be sent to the client on the output queue.

    The main entrypoint to this class is filter_queue().
    We want the work done in filter_queue() to be done off the main server thread.
    """

    def __init__(self, invocation_context: InvocationContext,
                 template_response_dict: Dict[str, Any],
                 chat_filter: Dict[str, Any],
                 agent_network: AgentNetwork):
        """
        Constructor

        :param invocation_context: An instance of InvocationContext
        :param template_response_dict: A dictionary form of chat.ChatResponse
        :param chat_filter: A dictionary form of chat.ChatFilter
        :param agent_network: An instance of AgentNetwork
        """
        self.input_queue: AsyncCollatingQueue = invocation_context.get_queue()
        self.output_queue: AsyncCollatingQueue = invocation_context.get_filtered_queue()
        self.template_response_dict: Dict[str, Any] = template_response_dict

        self.message_filter: MessageFilter = MessageFilterFactory.create_message_filter(chat_filter)
        self.message_processor: MessageProcessor = self.create_outgoing_message_processor(agent_network)

    def create_outgoing_message_processor(self, agent_network: AgentNetwork) -> MessageProcessor:
        """
        :param agent_network: An instance of AgentNetwork
        :return: A MessageProcessor that filters messages outgoing to the client.
                How this works is based on settings on the front man.
                Can be None.
        """
        message_processor: MessageProcessor = None

        front_man_name: str = agent_network.find_front_man()
        front_man_spec: Dict[str, Any] = agent_network.get_agent_tool_spec(front_man_name)

        # Get the formats we should parse from the final answer from the config for the network.
        # As of 6/24/25, this is an unadvertised experimental feature.
        structure_formats: Union[str, List[str]] = front_man_spec.get("structure_formats")
        if structure_formats is None:
            return message_processor

        # Eventually this might be a CompositeMessageProcessor
        message_processor = StructureMessageProcessor(structure_formats)
        return message_processor

    async def filter_queue(self):
        """
        Main task entry point for DirectAgentSession.
        Filter the messages coming off the input queue so that they can be sent to the client
        via the output queue.
        We'd rather this work be done off the main server thread.
        """
        try:
            async for message in self.input_queue:
                response_dict = await self.process_queue_message(message)
                if response_dict is not None:
                    await self.output_queue.put(response_dict, synchronous=True)
        finally:
            # Always signal completion so consumers don't hang if processing fails mid-stream.
            try:
                await self.output_queue.put_final_item(synchronous=True)
            except Exception:
                pass
    async def process_queue_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process the single message and return an appropriate response dictionary

        :param message: A dictionary form of chat.ChatMessage
        :return: A dictionary form of chat.ChatResponse
        """
        if not self.message_filter.allow(message):
            return None

        # We expect the message to be a dictionary form of chat.ChatMessage
        if self.message_processor is not None:
            message_type: ChatMessageType = message.get("type")
            # Can modify message
            await self.message_processor.async_process_message(message, message_type)

        response_dict: Dict[str, Any] = copy(self.template_response_dict)
        response_dict["response"] = message
        return response_dict
