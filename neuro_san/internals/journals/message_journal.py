
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
from typing import List

from langchain_core.messages.base import BaseMessage

from neuro_san.internals.interfaces.async_hopper import AsyncHopper
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.base_message_dictionary_converter import BaseMessageDictionaryConverter


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

        # Queue Producer from this:
        #   https://stackoverflow.com/questions/74130544/asyncio-yielding-results-from-multiple-futures-as-they-arrive
        # The synchronous=True is necessary when an async HTTP request is at the get()-ing end of the queue,
        # as the journal messages come from inside a separate event loop from that request. The lock
        # taken here ends up being harmless in the synchronous request case (like for gRPC) because
        # we would only be blocking our own event loop.
        await self.hopper.put(message_dict, synchronous=True)
