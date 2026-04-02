
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

import uuid

from neuro_san.internals.run_context.interfaces.tool_call import ToolCall


class LangChainToolCall(ToolCall):
    """
    A LangChain implementation of a ToolCall

    For the uninitiated: A "ToolCall" in langchain/openai parlance is a *request*
    that a tool be called with certain structured function arguments.
    """

    def __init__(self, tool_name: str, args: Any, run_id: str, invocation: str = None):
        """
        Constructor

        :param tool_name: The name of the tool to be called
        :param args: The arguments the tool is requested to be called with
                So far we've only seen this as Dict[str, Any], but the langchain
                typing is Any, so we stick with that.
        :param run_id: The string id of the parent run so that the tool's
                    ids can be associated with that.
        :param invocation: String describing how the tool wants to be invoked.
                            Can be: "chatbot" - implies waiting for an answer.
                                    "event" - implies no answer needed
                                    None - implies chatbot
        """
        self.tool_name: str = tool_name
        self.args = args
        self.id: str = f"tool_call_{run_id}_{uuid.uuid4()}"
        self.invocation: str = invocation
        if invocation is None:
            self.invocation = "chatbot"

    def get_id(self) -> str:
        """
        :return: The string id of this run
        """
        return self.id

    def get_function_arguments(self) -> Dict[str, Any]:
        """
        :return: Returns a dictionary of the function arguments for the tool call
        """
        return self.args

    def get_function_name(self) -> str:
        """
        :return: Returns the string name of the tool
        """
        return self.tool_name

    def get_invocation(self) -> str:
        """
        :return: String describing how the tool wants to be invoked.
                            Can be: "chatbot" - implies waiting for an answer.
                                    "event" - implies no answer needed
                                    None - implies chatbot
        """
        return self.invocation
