
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

from pytest import raises

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage

from neuro_san.internals.run_context.utils.activation_capsule import ActivationCapsule

from tests.neuro_san.message.content_fixtures import ContentFixtures


class TestActivationCapsule(IsolatedAsyncioTestCase):
    """
    Tests for the return contract of ActivationCapsule.use_tool.

    use_tool is documented to return a str, but it used to return the
    sub-agent's raw message content. Today that content is always a str
    (the sub-agent's chain output is flattened before it is journaled), so
    the projection is an identity; once native block content is preserved
    through that message, the projection is what keeps the str contract.
    These tests lock it and confirm that plain-string content is returned
    untouched. They also check that use_reservation delegates to use_tool.
    """

    @staticmethod
    def make_capsule(build_result: BaseMessage) -> ActivationCapsule:
        """
        Build a capsule wired with a factory whose activation builds to the given message.

        :param build_result: The BaseMessage the sub-agent's build() will return
        :return: An ActivationCapsule whose factory yields an activation
                 that builds to the given message
        """
        callable_activation: MagicMock = MagicMock()
        callable_activation.build = AsyncMock(return_value=build_result)

        factory: MagicMock = MagicMock()
        factory.create_agent_activation = MagicMock(return_value=callable_activation)

        return ActivationCapsule(parent_run_context=MagicMock(),
                                 parent_agent_spec={"name": "caller"},
                                 agent_tool_factory=factory)

    async def test_use_tool_returns_str_content_unchanged(self) -> None:
        """
        Plain-string content is returned exactly as-is: no stripping, no wrapping.
        """
        capsule: ActivationCapsule = self.make_capsule(AIMessage(content="  the answer  "))
        result: str = await capsule.use_tool("sub_agent", {"arg": "value"}, {})
        assert result == "  the answer  "

    async def test_use_tool_projects_block_content_to_text(self) -> None:
        """
        Thinking-first block content from the sub-agent comes back as its text,
        honoring the documented str contract instead of leaking a list repr.
        """
        capsule: ActivationCapsule = self.make_capsule(ContentFixtures.anthropic_thinking_first())
        result: str = await capsule.use_tool("sub_agent", {"arg": "value"}, {})
        assert isinstance(result, str)
        assert result == "the answer"

    async def test_use_tool_requires_factory_and_spec(self) -> None:
        """
        A capsule created without a factory or parent spec cannot call tools
        and says so, rather than failing deep inside the call.
        """
        capsule: ActivationCapsule = ActivationCapsule(parent_run_context=MagicMock())
        with raises(ValueError):
            await capsule.use_tool("sub_agent", {}, {})

    async def test_use_reservation_calls_use_tool_with_reservation_id(self) -> None:
        """
        use_reservation() delegates to use_tool() with "/<reservation_id>" as the tool name,
        passes args and sly_data through, and returns use_tool()'s result.
        """
        reservation: MagicMock = MagicMock()
        reservation.get_reservation_id = MagicMock(return_value="copy_cat-1234")

        capsule: ActivationCapsule = self.make_capsule(AIMessage(content="unused"))
        capsule.use_tool = AsyncMock(return_value="the answer")

        args: Dict[str, Any] = {"arg": "value"}
        sly_data: Dict[str, Any] = {"secret": "shh"}
        result: str = await capsule.use_reservation(reservation, args, sly_data)

        capsule.use_tool.assert_awaited_once_with("/copy_cat-1234", args, sly_data)
        self.assertEqual(result, "the answer")
