
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

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.system import SystemMessage

from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.agent_tool_result_message import AgentToolResultMessage
from neuro_san.internals.messages.base_message_dictionary_converter import BaseMessageDictionaryConverter


class OriginatingJournal(Journal):
    """
    A Journal implementation that has an origin.
    """

    def __init__(self, wrapped_journal: Journal,
                 origin: List[Dict[str, Any]],
                 chat_history: List[BaseMessage] = None):
        """
        Constructor

        :param wrapped_journal: The Journal that this implementation wraps
        :param origin: The origin that will be applied to all messages.
        :param chat_history: The chat history list instance to store write_message() results in.
                            Can be None (the default).
        """
        self.wrapped_journal: Journal = wrapped_journal
        self.origin: List[Dict[str, Any]] = origin
        self.chat_history: List[BaseMessage] = chat_history
        self.pending: BaseMessage = None

    def get_origin(self) -> List[Dict[str, Any]]:
        """
        :return: The origin associated with this Journal
        """
        return self.origin

    async def write_message(self, message: BaseMessage, origin: List[Dict[str, Any]] = None):
        """
        Writes a BaseMessage entry into the wrapped_journal
        and appends to the chat history.

        :param message: The BaseMessage instance to write to the wrapped_journal
        :param origin: A List of origin dictionaries indicating the origin of the run.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
                For this particular implementation we expect this to be None
        """
        use_origin: List[Dict[str, Any]] = self.origin
        if origin is not None:
            use_origin = origin

        if self.chat_history is not None and BaseMessageDictionaryConverter.is_relevant_to_chat_history(message):
            # Different LLM providers handle message types differently when constructing responses:
            #
            # - Anthropic models (via ChatAnthropic) explicitly check the `message.type` string
            #   and only accept messages of type "human" or "ai". Custom subclasses like
            #   AgentToolResultMessage return a different type (e.g., "agent_tool_result"),
            #   which causes Anthropic's handler to reject the message.
            #
            #
            # - OpenAI and Ollama models (via ChatOpenAI and ChatOllama) do not rely on `message.type`.
            #   Instead, they use `isinstance(message, AIMessage)` checks, which allows us to safely pass
            #   `AgentToolResultMessage` since it subclasses `AIMessage`. This gives us the flexibility
            #   to include additional metadata like `tool_result_origin` when supported.
            #
            # To avoid problem with any other LLMs, convert "AgentToolResultMessage" to "AIMessage"
            # when appending it chathistory but allow it to be written in the journal as is to
            # to maintain the information on tool origin.
            if isinstance(message, AgentToolResultMessage):
                message = AIMessage(content=message.content)

            # Langchain automatically adds the system prompt to the beginning of the chat history.
            # Don’t add it here to avoid duplication.
            if not isinstance(message, SystemMessage):
                self.chat_history.append(message)

        if self.pending is not None:
            # Avoid cases where two different kinds of message hold the same content.
            if self.pending.content != message.content:
                await self.wrapped_journal.write_message(self.pending, use_origin)
            self.pending = None

        await self.wrapped_journal.write_message(message, use_origin)

    def get_chat_history(self) -> List[BaseMessage]:
        """
        :return: The chat history list of base messages associated with the instance.
        """
        return self.chat_history

    async def write_message_if_next_not_dupe(self, message: BaseMessage):
        """
        Writes a BaseMessage entry into the wrapped_journal
        and appends to the chat history as long as the next message does not have the same content.

        :param message: The BaseMessage instance to write to the wrapped_journal
        """
        if self.pending is not None:
            # Flush if anything is already waiting.
            await self.write_message(self.pending)
        self.pending = message
