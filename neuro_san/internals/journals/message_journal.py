
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

from langchain_core.messages.base import BaseMessage

from neuro_san.internals.filters.maximal_message_filter import MaximalMessageFilter
from neuro_san.internals.filters.message_filter import MessageFilter
from neuro_san.internals.interfaces.async_hopper import AsyncHopper
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.base_message_dictionary_converter import BaseMessageDictionaryConverter
from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.message_processing.message_processor import MessageProcessor


class MessageJournal(Journal):
    """
    Journal implementation for putting entries into a Hopper
    for storage for later processing.
    """

    def __init__(self, hopper: AsyncHopper):
        """
        Constructor

        :param hopper: A handle to an AsyncHopper implementation, onto which
                       any message will be put().
        """
        self.hopper: AsyncHopper = hopper
        self.message_filter: MessageFilter = MaximalMessageFilter()
        self.message_processor: MessageProcessor = None
        self.issue_response_dicts: bool = True

    def set_message_filter(self, message_filter: MessageFilter):
        """
        Sets the message filter for this journal.
        """
        self.message_filter = message_filter

    def set_message_processor(self, message_processor: MessageProcessor):
        """
        Sets the message processor for this journal.
        """
        self.message_processor = message_processor

    async def write_message(self, message: BaseMessage, origin: List[Dict[str, Any]]):
        """
        Writes a BaseMessage entry into the journal
        :param message: The BaseMessage instance to write to the journal
        :param origin: A List of origin dictionaries indicating the origin of the run.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
        """
        converter = BaseMessageDictionaryConverter(origin=origin)
        message_dict: Dict[str, Any] = converter.to_dict(message)
        message_type: ChatMessageType = message_dict.get("type")

        if not self.message_filter.allow_message(message_dict, message_type):
            return

        if self.message_processor is not None:
            # Can modify message_dict
            await self.message_processor.async_process_message(message_dict, message_type)

        outgoing_dict: Dict[str, Any] = message_dict
        if self.issue_response_dicts:
            outgoing_dict = {"response": message_dict}

        # Queue Producer from this:
        #   https://stackoverflow.com/questions/74130544/asyncio-yielding-results-from-multiple-futures-as-they-arrive
        # The synchronous=True is necessary when an async HTTP request is at the get()-ing end of the queue,
        # as the journal messages come from inside a separate event loop from that request. The lock
        # taken here ends up being harmless in the synchronous request case (like for gRPC) because
        # we would only be blocking our own event loop.
        await self.hopper.put(outgoing_dict, synchronous=True)
