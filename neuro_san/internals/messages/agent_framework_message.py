
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
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Literal
from typing import Optional
from typing import Tuple
from typing import Union

from copy import copy

from neuro_san.internals.messages.traced_message import TracedMessage


class AgentFrameworkMessage(TracedMessage):
    """
    TracedMessage implementation of a message from the agent framework
    """

    structure: Optional[Dict[str, Any]] = None
    sly_data: Optional[Dict[str, Any]] = None
    chat_context: Optional[Dict[str, Any]] = None

    type: Literal["agent-framework"] = "agent-framework"

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def __init__(self, content: Union[str, List[Union[str, Dict]]] = "",
                 chat_context: Dict[str, Any] = None,
                 sly_data: Dict[str, Any] = None,
                 structure: Dict[str, Any] = None,
                 trace_source: AgentFrameworkMessage = None,
                 **kwargs: Any) -> None:
        """
        Pass in content as positional arg.

        :param content: The string contents of the message.
        :param chat_context: A dictionary that fully desbribes the state of play
                    of the chat conversation such that when it is passed on to a
                    different server, the conversation can continue uninterrupted.
        :param sly_data: A dictionary of private data, separate from the chat stream.
        :param structure: A dictionary previously extracted from the content
                        that had been optionally detected by the system as JSON text.
                        The idea is to have the server do the hard parsing so the
                        multitude of clients do not have to rediscover how to best do it.
        :param trace_source: A message of the same type to prepare for tracing display
        :param kwargs: Additional fields to pass to the superclass
        """
        super().__init__(content=content, trace_source=trace_source, **kwargs)

        self.chat_context: Dict[str, Any] = chat_context
        if chat_context is None:
            # Special case default so that the MinimalMessageFilter, which only
            # looks for chat_context, does not fail to send the final AgentFrameworkMessage.
            self.chat_context = {}

        self.sly_data: Dict[str, Any] = sly_data
        self.structure: Dict[str, Any] = structure

    @property
    def lc_kwargs(self) -> Dict[str, Any]:
        """
        :return: the keyword arguments for serialization.
        """
        return {
            "content": self.content,
            "structure": self.structure,
            "sly_data": self.sly_data,
            "chat_context": self.chat_context,
        }

    def translate_for_trace(self, key: str, value: Any) -> Tuple[str, Any]:
        """
        :param key: The key to consider/translate.
        :param value: The value to consider/translate
        :return: A tuple with the new key and new value to be shown in the trace.
                New keys that are None are not included in the additional_kwargs.
                The default implementation simply ensures that there is something in the
                value to trace display to maximize information.
        """
        new_key, new_value = super().translate_for_trace(key, value)
        if not new_key:
            return None, None

        # Specifically redact any sly_data values, but keep the keys.
        # The intent here is to not transmit any sensitive information
        # that might make it to some other host.
        if new_key == "sly_data":
            # Shallow copy the original sly_data dictionary
            new_value = copy(value)
            for sly_data_key in new_value:
                # Keep the keys but redact the values
                new_value[sly_data_key] = "<redacted>"

        return new_key, new_value
