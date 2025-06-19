
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
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.system import SystemMessage
from langchain_core.messages.tool import ToolMessage

from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.messages.agent_framework_message import AgentFrameworkMessage
from neuro_san.internals.messages.agent_tool_result_message import AgentToolResultMessage
from neuro_san.internals.messages.chat_message_type import ChatMessageType


def convert_to_chat_message(message: BaseMessage, origin: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Convert the BaseMessage to a chat.ChatMessage dictionary

    :param message: The BaseMessage to convert
    :param origin: A List of origin dictionaries indicating the origin of the run.
            The origin can be considered a path to the original call to the front-man.
            Origin dictionaries themselves each have the following keys:
                "tool"                  The string name of the tool in the spec
                "instantiation_index"   An integer indicating which incarnation
                                        of the tool is being dealt with.
    :return: The ChatMessage in dictionary form
    """

    message_type: ChatMessageType = ChatMessageType.from_message(message)
    chat_message: Dict[str, Any] = {
        "type": message_type,
        # No mime_data for now
    }

    # Handle the origin information if we have it
    if origin is not None:
        chat_message["origin"] = origin

    # Dictionary of BaseMessage field sources to ChatMessage destinations
    # Anything in this dictionary is considered optional and we only populate
    # the field on ChatMessage if it has a value.
    optionals: Dict[str, str] = {
        "content": "text",
        "chat_context": "chat_context",
        "tool_result_origin": "tool_result_origin",
        "structure": "structure",
        "sly_data": "sly_data",
    }
    for src, dest in optionals.items():
        value: Any = None
        try:
            value = getattr(message, src)
        except AttributeError:
            # Not all BaseMessage subclasses have every field we are looking
            # for, and that is ok.
            value = None

        # For OpenAI and Ollama, content of AI message is a string but content from
        # Anthropic AI message can either be a single string or a list of content blocks.
        # If it is a list, "text" is a key of a dictionary which is the first element of
        # the list. For more details: https://python.langchain.com/docs/integrations/chat/anthropic/#content-blocks
        if src == "content" and isinstance(value, list):
            if len(value) > 0:
                value = value[0].get("text", "")
            else:
                value = None

        if value is not None:
            chat_message[dest] = value

    return chat_message


def convert_to_base_message(chat_message: Dict[str, Any], langchain_only: bool = True) -> BaseMessage:
    """
    The intended use for this method is for converting a neuro-san ChatMessage
    dictionary into a langchain BaseMessage such that it can be understood by
    a langchain agent within the context of a langchain-facing chat history.
    This means that some special messages we might have inserted into a chat
    history *might* need to be converted into something langchain agents will
    understand.

    :param chat_message: A ChatMessage dictionary to convert into BaseMessage
    :param langchain_only: When True (default) only convert langchain messages,
                        and not our own special variants.
    :return: A BaseMessage that was converted from the input.
            Can return None if conversion could not take place
    """
    base_message: BaseMessage = None
    if chat_message is None:
        return base_message

    content: str = chat_message.get("text")
    chat_message_type: ChatMessageType = ChatMessageType.from_response_type(chat_message.get("type"))

    if chat_message_type == ChatMessageType.SYSTEM:
        base_message = SystemMessage(content=content)
    elif chat_message_type == ChatMessageType.HUMAN:
        base_message = HumanMessage(content=content)
    elif chat_message_type == ChatMessageType.AI:
        base_message = AIMessage(content=content)
    elif chat_message_type == ChatMessageType.AGENT_TOOL_RESULT:
        base_message = AgentToolResultMessage(content=content,
                                              tool_result_origin=chat_message.get("tool_result_origin"))

    if langchain_only:
        # Go no further
        return base_message

    if base_message is None:
        # convert_to_base_message() is primarily for populating langchain chat history.
        # so handle these other types differently.
        if chat_message_type == ChatMessageType.AGENT:
            base_message = AgentMessage(content=chat_message.get("text", ""),
                                        structure=chat_message.get("structure"))
        elif chat_message_type == ChatMessageType.AGENT_FRAMEWORK:
            # Don't bother passing on chat_context
            base_message = AgentFrameworkMessage(content=chat_message.get("text", ""))

    # Any other message type we do not want to send to any agent as chat history.

    return base_message


def is_relevant_to_chat_history(base_message: BaseMessage) -> bool:
    """
    :param base_message: The BaseMessage to consider
    :return: True if the BaseMessage type is relevant to chat history (include).
             False otherwise (do not include).
    """
    if isinstance(base_message, (AgentMessage, AgentFrameworkMessage, ToolMessage)):
        # These guys cannot be in chat history as langchain will not recognize them.
        return False
    return True
