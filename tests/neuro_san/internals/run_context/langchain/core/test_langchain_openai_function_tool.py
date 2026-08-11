
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

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from neuro_san.internals.run_context.langchain.core.langchain_openai_function_tool \
    import LangChainOpenAIFunctionTool
from neuro_san.internals.run_context.langchain.core.langchain_run import LangChainRun
from neuro_san.message.types.agent_tool_result_message import AgentToolResultMessage


class TestLangChainOpenAIFunctionTool:
    """
    Test cases for what _arun() hands back to langchain as the tool output.

    Whatever _arun() returns becomes the ToolMessage content the calling LLM
    sees: langchain passes str and content-block list returns through as-is,
    but falls back to str() for any other object.  Returning a BaseMessage
    would therefore expose its pydantic repr ("content='...'
    additional_kwargs={} ...") to the calling LLM instead of the answer.
    """

    @staticmethod
    def make_tool(run_to_return: LangChainRun = None,
                  exception: Exception = None) -> LangChainOpenAIFunctionTool:
        """
        :param run_to_return: The Run for the mock ToolCaller to hand back
        :param exception: Optional exception for the mock ToolCaller to raise instead
        :return: A minimal LangChainOpenAIFunctionTool wired to the mock ToolCaller
        """
        tool_caller = MagicMock()
        if exception is not None:
            tool_caller.make_tool_function_calls = AsyncMock(side_effect=exception)
        else:
            tool_caller.make_tool_function_calls = AsyncMock(return_value=run_to_return)

        return LangChainOpenAIFunctionTool.model_construct(
            name="test_tool",
            description="a test tool",
            tool_caller=tool_caller)

    @pytest.mark.asyncio
    async def test_arun_returns_message_content_not_message_object(self):
        """
        The sub-agent's answer must come back as the message content,
        not as the AgentToolResultMessage object itself.
        """
        the_message = AgentToolResultMessage(content="the answer",
                                             tool_result_origin=[{"tool": "test_tool",
                                                                  "instantiation_index": 0}])
        run = LangChainRun("tool_base", [], tool_message=the_message)
        tool = self.make_tool(run_to_return=run)

        result = await tool._arun()   # pylint: disable=protected-access

        assert result == "the answer"
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_arun_returns_none_when_run_has_no_tool_message(self):
        """
        A Run can legitimately carry no tool message (see submit_tool_outputs()
        when there are no parseable tool outputs). _arun() must not blow up
        dereferencing content on None.
        """
        run = LangChainRun("tool_base", [], tool_message=None)
        tool = self.make_tool(run_to_return=run)

        result = await tool._arun()   # pylint: disable=protected-access

        assert result is None

    @pytest.mark.asyncio
    async def test_arun_returns_exception_string_on_failure(self):
        """
        Exceptions from the tool call are reported back to the calling LLM
        as their string form so it can verbally recognize the problem.
        """
        tool = self.make_tool(exception=ValueError("something broke"))

        result = await tool._arun()   # pylint: disable=protected-access

        assert result == "something broke"
