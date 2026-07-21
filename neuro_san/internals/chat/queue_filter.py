
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

from copy import copy

from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.filters.message_filter import MessageFilter
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.message_processing.message_processor import MessageProcessor


class QueueFilter:
    """
    """

    def __init__(self, invocation_context: InvocationContext,
                 template_response_dict: Dict[str, Any],
                 message_filter: MessageFilter,
                 message_processor: MessageProcessor):
        """
        Constructor

        :param input_queue: The queue we will be iterating over.
        :param output_queue: The queue we will be iterating over.
        """
        self.input_queue: AsyncCollatingQueue = invocation_context.get_queue()
        self.output_queue: AsyncCollatingQueue = invocation_context.get_filtered_queue()
        self.template_response_dict: Dict[str, Any] = template_response_dict
        self.message_filter: MessageFilter = message_filter
        self.message_processor: MessageProcessor = message_processor

    async def filter_queue(self):

        response_dict: Dict[str, Any] = None
        async for message in self.input_queue:
            response_dict = await self.process_queue_message(message)
            if response_dict is not None:
                await self.output_queue.put(response_dict, synchronous=True)

        await self.output_queue.put_final_item(synchronous=True)

    async def process_queue_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process the message and return an appropriate response dictionary
        This is called by the server main loop in streaming_chat() to filter
        what needs to be sent to the client.
        We'd rather this be done on the DataDrivenChatSession side of the queue.

        :param message: A dictionary form of chat.ChatMessage
        :param template_response_dict: A dictionary form of chat.ChatResponse
        :param message_filter: An instance of MessageFilter
        :param message_processor: An instance of MessageProcessor
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
