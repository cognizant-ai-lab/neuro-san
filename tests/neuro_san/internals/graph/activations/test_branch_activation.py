
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

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage

from neuro_san.internals.graph.activations.branch_activation import BranchActivation
from neuro_san.internals.graph.filters.network_config_filter_chain import NetworkConfigFilterChain

from tests.neuro_san.message.content_fixtures import ContentFixtures


class TestBranchActivation(IsolatedAsyncioTestCase):
    """
    Tests for the return contract of BranchActivation.use_tool, and for the
    assignments a sub-agent receives from its caller.

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

    async def test_use_tool_returns_str_content_unchanged(self) -> None:
        """
        Plain-string content is returned exactly as-is: no stripping, no wrapping.
        """
        activation: BranchActivation = self.make_activation(AIMessage(content="  the answer  "))
        result: str = await activation.use_tool("sub_agent", {"arg": "value"}, {})
        assert result == "  the answer  "

    async def test_use_tool_projects_block_content_to_text(self) -> None:
        """
        Thinking-first block content from the sub-agent comes back as its text,
        honoring the documented str contract instead of leaking a list repr.
        """
        activation: BranchActivation = self.make_activation(ContentFixtures.anthropic_thinking_first())
        result: str = await activation.use_tool("sub_agent", {"arg": "value"}, {})
        assert isinstance(result, str)
        assert result == "the answer"

    async def test_use_tool_releases_sub_activation_resources(self) -> None:
        """
        The sub-agent activation's close_of_work() is always awaited with the
        caller's run context, so its LLM resources are not orphaned.
        """
        activation: BranchActivation = self.make_activation(AIMessage(content="the answer"))
        await activation.use_tool("sub_agent", {}, {})

        callable_activation: MagicMock = activation.factory.create_agent_activation.return_value
        callable_activation.close_of_work.assert_awaited_once_with(activation.run_context)

    def test_sub_agent_without_parameters_gets_every_argument(self) -> None:
        """
        A sub-agent that declares no parameters, whether it gives a top-level description
        or a function block without parameters, gets every argument its caller sends:
        the inquiry that an LLM sends through the default parameter of its tool, or the
        arguments that a coded tool chooses.
        """
        helpers: Dict[str, Dict[str, Any]] = {
            "top_level_description": {
                "name": "helper",
                "description": "Answers questions.",
            },
            "function_without_parameters": {
                "name": "helper",
                "function": {
                    "description": "Answers questions.",
                },
            },
        }

        # Each caller maps the arguments it sends to the message the sub-agent must get.
        callers: Dict[str, Dict[str, Any]] = {
            "llm": {
                "arguments": {
                    "inquiry": "Recommend a novel like Dune",
                },
                "message": "The inquiry is Recommend a novel like Dune.",
            },
            "coded_tool": {
                "arguments": {
                    "agent_name": "fiction_recommender",
                    "change_request": "Make it shorter",
                },
                "message": "The agent_name is fiction_recommender.\nThe change_request is Make it shorter.",
            },
        }

        # The labels are strings, so the subTest parameters stay picklable under pytest-xdist.
        helper_label: str = None
        caller_label: str = None
        # Try each way of declaring no parameters.
        for helper_label in helpers:
            # Try each kind of caller against it.
            for caller_label in callers:
                with self.subTest(helper=helper_label, caller=caller_label):
                    config: Dict[str, Any] = {
                        "tools": [
                            {
                                "name": "front",
                                "tools": ["helper"],
                            },
                            helpers.get(helper_label),
                        ],
                    }
                    filtered: Dict[str, Any] = NetworkConfigFilterChain().filter_config(config)
                    caller: Dict[str, Any] = callers.get(caller_label)

                    # Skip the constructor, which creates a real RunContext.
                    activation: BranchActivation = BranchActivation.__new__(BranchActivation)
                    activation.agent_tool_spec = filtered.get("tools")[1]
                    activation.arguments = caller.get("arguments")

                    self.assertEqual(activation.get_assignments(), caller.get("message"))
