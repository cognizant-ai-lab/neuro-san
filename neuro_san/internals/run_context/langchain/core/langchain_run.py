
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
from typing import List

from langchain_core.messages.base import BaseMessage

from neuro_san.internals.run_context.interfaces.run import Run
from neuro_san.internals.run_context.interfaces.tool_call import ToolCall
from neuro_san.internals.run_context.langchain.core.langchain_tool_call import LangChainToolCall


class LangChainRun(Run):
    """
    A LangChain implementation of a Run.
    """

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(self, run_id_base: str, chat_history: List[BaseMessage], tool_name: str = None,
                 args: Any = None, tool_message: BaseMessage = None, invocation: str = None):
        """
        Constructor

        :param run_id_base: The basis string for run ids.
        :param chat_history: The chat history so far
        :param tool_name: The name of the tool to call
        :param args: The arguments used for the tool during the run
                    represented by this instance.
        :param tool_message: The most recent tool message produced during the run
                             represented by this instance.
        :param invocation: String describing how the tool wants to be invoked.
                            Can be: "chatbot" - implies waiting for an answer.
                                    "event" - implies no answer needed
                                    None - implies chatbot
        """
        self.id: str = self._create_run_id(run_id_base, chat_history)
        self.chat_history: List[BaseMessage] = chat_history
        self.tool_name: str = tool_name
        self.args: Any = args
        self.tool_message: BaseMessage = tool_message
        self.invocation: str = invocation

    @staticmethod
    def _create_run_id(run_id_base: str, chat_history: List[BaseMessage]) -> str:
        """
        :return: A run id string based on the uuid in run_id_base and
                 the length of the chat history so far.
        """
        chat_length = len(chat_history)

        # Zero pad the chat_length out to 4 digits.
        run_id: str = f"run_{run_id_base}_{chat_length:04}"
        return run_id

    def get_id(self) -> str:
        """
        :return: The string id of this run
        """
        return self.id

    def requires_action(self) -> bool:
        """
        :return: True if the status of the run requires external action.
                 False otherwise
        """
        # This allows the higher level check in branch tools
        # to know that we are doing something.
        return False

    def get_tool_calls(self) -> List[ToolCall]:
        """
        :return: A list of ToolCalls.
        """
        # At least return an empty list
        tool_calls: List[ToolCall] = []
        if self.args is not None:
            # We don't yet know how to get the list of tools an AgentExecutor actually
            # wants to call (as opposed to the list it *can( call, which is in the spec).
            # It probably has something to do with adding a CallbackManagerForChainRun
            # which somehow would get its on_agent_action() called when a tool is chosen in
            # AgentExecutor._perform_agent_action().  We'd probably need to set that up
            # and allow it to add tools/args to this run instance.
            #
            # For now, we just do a single tool given the run...
            # Create a ToolCall with the correct args and add that to the ToolCalls list
            tool_call: LangChainToolCall = LangChainToolCall(self.tool_name, self.args, self.id,
                                                             invocation=self.invocation)
            tool_calls.append(tool_call)

        return tool_calls

    def model_dump_json(self) -> str:
        """
        :return: This object as a JSON string
        """
        return "{ " + f"'id': '{self.id}'" + " }"

    def get_chat_history(self) -> List[BaseMessage]:
        """
        Get the most recent chat history.
        :return: The list of messages comprising the chat history
        """
        return self.chat_history

    def get_tool_message(self) -> BaseMessage:
        """
        This is used when the LangChainOpenAIFunctionTool wants to
        know what the most recent message was from the tool as
        its output.
        :return: The tool message comprising the tool output
        """
        return self.tool_message
