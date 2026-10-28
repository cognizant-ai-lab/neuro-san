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

from unittest.mock import MagicMock

from neuro_san.internals.run_context.langchain.core.run_context_runnable import RunContextRunnable


class RunContextRunnableTestHelpers:
    """
    Helpers shared by the RunContextRunnable test modules.

    They build a runnable whose error detector passes output through, and
    stand-in streams for agent_chain.astream().
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
