
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
from typing import Literal
from typing import Union

from langchain_core.messages.base import BaseMessage


class AgentFrameworkMessage(BaseMessage):
    """
    BaseMessage implementation of a message from the agent framework
    """

    type: Literal["agent-framework"] = "agent-framework"

    def __init__(self, content: Union[str, List[Union[str, Dict]]] = None,
                 chat_context: Dict[str, Any] = None,
                 sly_data: Dict[str, Any] = None,
                 **kwargs: Any) -> None:
        """
        Pass in content as positional arg.

        :param content: The string contents of the message.
        :param chat_context: A dictionary that fully desbribes the state of play
                    of the chat conversation such that when it is passed on to a
                    different server, the conversation can continue uninterrupted.
        :param sly_data: A dictionary of private data, separate from the chat stream.
        :param kwargs: Additional fields to pass to the superclass
        """
        super().__init__(content=content, **kwargs)
        self.chat_context: Dict[str, Any] = chat_context
        self.sly_data: Dict[str, Any] = sly_data
