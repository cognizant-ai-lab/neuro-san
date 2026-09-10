
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

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage

from neuro_san.internals.graph.activations.branch_activation import BranchActivation

from tests.neuro_san.message.content_fixtures import ContentFixtures


class TestBranchActivation:
    """
    Tests for the return contract of BranchActivation.use_tool.

    use_tool is documented to return a str, but it used to return the
    sub-agent's raw message content. Today that content is always a str
    (the sub-agent's chain output is flattened before it is journaled), so
    the projection is an identity; once native block content is preserved
    through that message, callers such as the copy_cat Copyist, which
    f-string the value straight into the calling LLM's tool result, would
    otherwise see a Python repr of the block list. These tests lock the
    text projection and confirm that plain-string content is returned
    untouched.
    """

    @staticmethod
    def make_activation(build_result: BaseMessage) -> BranchActivation:
        """
        Build a BranchActivation without running its constructor (which
        creates a real RunContext), wired with a factory whose activation
        build() returns the given message.

        :param build_result: The BaseMessage the sub-agent's build() will return
        :return: A BranchActivation ready for use_tool()
        """
        activation: BranchActivation = BranchActivation.__new__(BranchActivation)
        activation.agent_tool_spec = {"name": "caller"}
        activation.run_context = MagicMock()

        callable_activation: MagicMock = MagicMock()
        callable_activation.build = AsyncMock(return_value=build_result)
        callable_activation.close_of_work = AsyncMock()

        activation.factory = MagicMock()
        activation.factory.create_agent_activation = MagicMock(return_value=callable_activation)
        return activation

    @pytest.mark.asyncio
    async def test_use_tool_returns_str_content_unchanged(self) -> None:
        """
        Plain-string content is returned exactly as-is: no stripping, no wrapping.
        """
        activation: BranchActivation = self.make_activation(AIMessage(content="  the answer  "))
        result: str = await activation.use_tool("sub_agent", {"arg": "value"}, {})
        assert result == "  the answer  "

    @pytest.mark.asyncio
    async def test_use_tool_projects_block_content_to_text(self) -> None:
        """
        Thinking-first block content from the sub-agent comes back as its text,
        honoring the documented str contract instead of leaking a list repr.
        """
        activation: BranchActivation = self.make_activation(ContentFixtures.anthropic_thinking_first())
        result: str = await activation.use_tool("sub_agent", {"arg": "value"}, {})
        assert isinstance(result, str)
        assert result == "the answer"

    @pytest.mark.asyncio
    async def test_use_tool_releases_sub_activation_resources(self) -> None:
        """
        The sub-agent activation's close_of_work() is always awaited with the
        caller's run context, so its LLM resources are not orphaned.
        """
        activation: BranchActivation = self.make_activation(AIMessage(content="the answer"))
        await activation.use_tool("sub_agent", {}, {})

        callable_activation: MagicMock = activation.factory.create_agent_activation.return_value
        callable_activation.close_of_work.assert_awaited_once_with(activation.run_context)
