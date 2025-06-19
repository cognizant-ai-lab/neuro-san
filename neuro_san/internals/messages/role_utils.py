
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
from typing import List
from typing import Union

import json

from langchain_core.messages.base import BaseMessage

from neuro_san.internals.messages.chat_message_type import ChatMessageType


class RoleUtils:
    """
    Utility class to parse messages with role information.
    This ancient style of message is used between agents and tool calls
    and is agnostic to OpenAI vs langchain.
    """

    @staticmethod
    def generate_response(the_messages: List[Any]) -> str:
        """
        :param the_messages: A list of messages. Could be OpenAI or langchain messages.
        :return: a JSON-ification of the list of messages.
        """
        response_list = []
        for index, one_message in enumerate(the_messages):
            # Duplicate the role message before every tool response role message
            role: str = RoleUtils.get_role(one_message)
            if role == "tool" and index > 0:
                previous_message = the_messages[index - 1]
                previous_role: str = RoleUtils.get_role(previous_message)
                if previous_role == "assistant":
                    new_message = {
                        "role": previous_role,
                        "content": RoleUtils.get_content(previous_message)
                    }
                    response_list.append(new_message)

            message_dict = {
                "role": role,
                "content": RoleUtils.get_content(one_message)
            }
            response_list.append(message_dict)

        return json.dumps(response_list)

    @staticmethod
    def get_role(message: Any) -> str:
        """
        :param message: Either an OpenAI message or a langchain BaseMessage
        :return: A string describing the role of the message
        """

        if hasattr(message, "role"):
            return message.role

        # Check the look-up table above
        role: str = ChatMessageType.message_to_role(message)
        if role is not None:
            return role

        raise ValueError(f"Don't know how to handle message type {message.__class__.__name__}")

    @staticmethod
    def get_content(message: Any) -> str:
        """
        :param message: Either an OpenAI message or a langchain BaseMessage
        :return: A string describing the content of the message
        """

        if isinstance(message, BaseMessage):
            # For OpenAI and Ollama, content of AI message is a string but content from
            # Anthropic AI message can either be a single string or a list of content blocks.
            # If it is a list, "text" is a key of a dictionary which is the first element of
            # the list. For more details: https://python.langchain.com/docs/integrations/chat/anthropic/#content-blocks
            content: Union[str, List] = message.content
            if isinstance(content, list):
                content = content[0].get("text", "")
            return content

        if hasattr(message, "content"):
            if not any(message.content):
                return ""
            return message.content[0].text.value

        raise ValueError(f"Don't know how to handle message type {message.__class__.__name__}")
