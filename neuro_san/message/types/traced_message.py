
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
from typing import Tuple
from typing import Union

from langchain_core.messages.base import BaseMessage


class TracedMessage(BaseMessage):
    """
    Absstract BaseMessage implementation of a message that is to be sent over
    to be displayed in an observability/tracing service like LangSmith.

    Note that these messages are intended to go to other services
    so any sensitive information should be redacted via an overridden
    translate_for_trace() method.

    As of 10/25/25:
    LangSmith will only show content in its trace viewer even when there are other
    fields filled in, even in additional kwargs. So this class makes all those fields
    visible by copying anything displayable into additional_kwargs and nulling out
    the content field when a trace_source message is provided in the constructor..
    """

    # Note this is an abstract class so we do not even define the type for it.

    def __init__(self, content: Union[str, List[Union[str, Dict]]] = "",
                 trace_source: TracedMessage = None,
                 **kwargs: Any) -> None:
        """
        Pass in content as positional arg.

        Args:
            content: The string contents of the message.
            trace_source: Another TracedMessage to copy additional_kwargs from.
            kwargs: Additional fields to pass to the
        """
        if trace_source:
            # If the content is set to something other than None or an empty string,
            # that is all that LangSmith will ever show.  So put what we want to show
            # in the additional_kwargs with effectively null content.
            additional_kwargs: Dict[str, Any] = trace_source.minimal_additional_kwargs()
            super().__init__(content="", additional_kwargs=additional_kwargs, **kwargs)
        else:
            super().__init__(content=content, **kwargs)

    @property
    def lc_serializable(self) -> bool:
        """
        Indicates if the object can be serialized by LangChain.
        """
        return True

    @property
    def lc_kwargs(self) -> Dict[str, Any]:
        """
        :return: the dictionary of keyword arguments for serialization.
        """
        raise NotImplementedError

    def minimal_additional_kwargs(self) -> Dict[str, Any]:
        """
        Creates a minimal additional_kwargs dictionary from the trace_source
        :return: The minimal kwargs dictionary
        """

        additional_kwargs: Dict[str, Any] = {}

        for key, value in self.lc_kwargs.items():
            new_key, new_value = self.translate_for_trace(key, value)
            if new_key is not None:
                additional_kwargs[new_key] = new_value

        return additional_kwargs

    def translate_for_trace(self, key: str, value: Any) -> Tuple[str, Any]:
        """
        :param key: The key to consider/translate.
        :param value: The value to consider/translate
        :return: A tuple with the new key and new value to be shown in the trace.
                New keys that are None are not included in the additional_kwargs.
                The default implementation simply ensures that there is something in the
                value to trace display to maximize information.
        """
        displayable: bool = value is not None and len(value) > 0
        if not displayable:
            return None, None

        return key, value
