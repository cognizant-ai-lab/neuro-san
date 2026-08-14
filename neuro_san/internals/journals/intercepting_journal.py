
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

from neuro_san.internals.journals.journal import Journal
from neuro_san.message.types.traced_message import TracedMessage


class InterceptingJournal(Journal):
    """
    A Journal implementation that intercepts messages for a specific origin en route
    to another wrapped Journal.
    """

    def __init__(self, wrapped_journal: Journal, origin: List[Dict[str, Any]]):
        """
        Constructor

        :param wrapped_journal: The journal to forward messages to
        :param origin: The origin dictionary to match for intercepts
        """
        self.wrapped_journal: Journal = wrapped_journal
        self.origin: List[Dict[str, Any]] = origin
        self.messages: List[BaseMessage] = []

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
        # Let the wrapped guy do what he's gunna do
        await self.wrapped_journal.write_message(message, origin)
        self.write_unwrapped_message(message, origin)

    def write_unwrapped_message(self, message: BaseMessage, origin: List[Dict[str, Any]]):
        """
        Write a message to this journal without going through the wrapped journal.

        :param message: The BaseMessage instance to write to the journal
        :param origin: A List of origin dictionaries indicating the origin of the run.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
        """

        # Only consider messages that match the same origin as what we care about.
        if origin == self.origin:

            new_message: BaseMessage = message

            # When messages are TracedMessages, capture a version that
            # has all their fields translated to the additional_kwargs
            # for better display in tracing/observability applications like
            # LangSmith.
            if isinstance(message, TracedMessage):
                new_message = message.__class__(trace_source=message)

            self.messages.append(new_message)

    def get_messages(self) -> List[BaseMessage]:
        """
        :return: the intercepted messages
        """
        return self.messages
