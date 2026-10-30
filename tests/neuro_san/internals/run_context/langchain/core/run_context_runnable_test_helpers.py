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
from typing import AsyncIterator
from typing import Dict
from typing import List

from unittest.mock import MagicMock

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.tool import ToolMessage

from neuro_san.internals.run_context.langchain.core.run_context_runnable import RunContextRunnable


class RunContextRunnableTestHelpers:
    """
    Helpers shared by the RunContextRunnable and ToolExchangeRecorder tests.

    They build a runnable whose error detector passes output through, stand-in
    streams for agent_chain.astream(), and the tool calls and chain state of a
    turn in which the model called a tool.
    """

    @staticmethod
    def passthrough(output: str) -> str:
        """
        Returns the given output unchanged, standing in for ErrorDetector.handle_error
        in tests that do not exercise error rewriting.

        :param output: The chain output text handed to the error detector
        :return: The same output, untouched
        """
        return output

    @staticmethod
    def make_runnable() -> RunContextRunnable:
        """
        Builds a RunContextRunnable with a pass-through error detector.

        :return: A runnable whose error detector is a pass-through
        """
        error_detector: MagicMock = MagicMock()
        error_detector.handle_error = MagicMock(side_effect=RunContextRunnableTestHelpers.passthrough)
        return RunContextRunnable.model_construct(error_detector=error_detector)

    @staticmethod
    async def state_stream(*states: Any) -> AsyncIterator[Any]:
        """
        Stands in for one agent_chain.astream() call: yields each state in turn.

        :param states: The states to yield; an exception among them is raised in its place
        :return: An async iterator over the states
        :raises BaseException: Any exception given among the states, when the stream reaches it
        """
        state: Any = None
        # Yield the states in order, failing where the chain would have failed.
        for state in states:
            if isinstance(state, BaseException):
                raise state
            yield state

    @staticmethod
    def stream_of(*states: Any, **_kwargs: Any) -> AsyncIterator[Any]:
        """
        Builds a fresh stand-in stream for every agent_chain.astream() call.

        :param states: The states to yield, bound with functools.partial
        :param _kwargs: The keyword arguments of the astream() call; ignored
        :return: An async iterator over the states
        """
        return RunContextRunnableTestHelpers.state_stream(*states)

    @staticmethod
    def tool_call(call_id: str) -> Dict[str, Any]:
        """
        Builds a tool call dictionary for the Accountant tool.

        :param call_id: The id of the tool call
        :return: A langchain tool call dictionary for the Accountant tool
        """
        return {
            "name": "Accountant",
            "args": {"running_cost": 0.0},
            "id": call_id,
            "type": "tool_call",
        }

    @staticmethod
    def tool_turn_state(human: HumanMessage) -> Dict[str, Any]:
        """
        Builds a chain state for a turn in which the model called a tool once.

        :param human: The user's message that started the turn
        :return: A state dict whose messages are an earlier exchange, the user's
                 message, a tool-calling AIMessage with Anthropic-shaped content,
                 the ToolMessage answering it, and the answer
        """
        tool_call: Dict[str, Any] = RunContextRunnableTestHelpers.tool_call("toolu_1")
        content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": "Let me check.",
            },
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "Accountant",
                "input": {"running_cost": 0.0},
            },
        ]
        calling: AIMessage = AIMessage(content=content, tool_calls=[tool_call])
        result: ToolMessage = ToolMessage(content="{'running_cost': 3.0}", tool_call_id="toolu_1", name="Accountant")
        return {"messages": [HumanMessage(content="earlier", id="h0"), AIMessage(content="earlier answer", id="a0"),
                             human, calling, result, AIMessage(content="the answer")]}
