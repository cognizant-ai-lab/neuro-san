
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


class AgentProgressMessage(BaseMessage):
    """
    BaseMessage implementation of a progress message from an agent or CodedTool
    """

    type: Literal["agent-progress"] = "agent-progress"

    def __init__(self, content: Union[str, List[Union[str, Dict]]] = "",
                 structure: Dict[str, Any] = None, **kwargs: Any) -> None:
        """
        Pass in content as positional arg.

        Args:
            content: The string contents of the message.
            structure: A dictionary to pack into the message
            kwargs: Additional fields to pass to the
        """
        super().__init__(content=content, **kwargs)
        self.structure: Dict[str, Any] = structure
