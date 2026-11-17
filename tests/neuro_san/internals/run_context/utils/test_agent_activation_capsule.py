
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

from neuro_san.internals.run_context.utils.agent_activation_capsule import AgentActivationCapsule

from tests.neuro_san.message.content_fixtures import ContentFixtures


class TestAgentActivationCapsule(IsolatedAsyncioTestCase):
    """
    Tests for the return contract of AgentActivationCapsule.use_tool.

    use_tool returns a str projected from the sub-agent's message content.
    That content is currently always a str (the sub-agent's chain output is
    flattened before it is journaled), so the projection is an identity; when
    native block content is preserved through that message, the projection
    keeps the str contract. These tests lock it and confirm that plain-string
    content is returned untouched. They also check that use_tool releases each sub-agent as soon
    as its call is done, that close_of_work releases every lingering resource
    exactly once, that use_reservation delegates to use_tool, and that
    create_session hands out factory sessions that close_of_work closes.
    """

    @staticmethod
    def make_capsule(build_result: BaseMessage) -> AgentActivationCapsule:
        """
        Build a capsule wired with a factory whose activation builds to the given message.

        :param build_result: The BaseMessage the sub-agent's build() will return
        :return: An AgentActivationCapsule whose factory yields an activation
                 that builds to the given message
        """
        callable_activation: MagicMock = MagicMock()
        callable_activation.build = AsyncMock(return_value=build_result)
        callable_activation.close_of_work = AsyncMock()

        factory: MagicMock = MagicMock()
        factory.create_agent_activation = MagicMock(return_value=callable_activation)

        return AgentActivationCapsule(parent_run_context=MagicMock(),
                                      parent_agent_spec={"name": "caller"},
                                      agent_tool_factory=factory)

    @staticmethod
    def make_session_capsule(session: MagicMock) -> AgentActivationCapsule:
        """
        Build a capsule whose invocation context's session factory returns the given session.

        :param session: The session the session factory will return
        :return: An AgentActivationCapsule wired to that session factory
        """
        session_factory: MagicMock = MagicMock()
        session_factory.async_create_session = AsyncMock(return_value=session)

        invocation_context: MagicMock = MagicMock()
        invocation_context.get_async_session_factory = MagicMock(return_value=session_factory)
        invocation_context.get_effective_invocation = MagicMock(return_value="chatbot")

        parent_run_context: MagicMock = MagicMock()
        parent_run_context.get_invocation_context = MagicMock(return_value=invocation_context)

        return AgentActivationCapsule(parent_run_context=parent_run_context)

    async def test_use_tool_returns_str_content_unchanged(self) -> None:
        """
        Plain-string content is returned exactly as-is: no stripping, no wrapping.
        """
        capsule: AgentActivationCapsule = self.make_capsule(AIMessage(content="  the answer  "))
        result: str = await capsule.use_tool("sub_agent", {"arg": "value"}, {})
        self.assertEqual(result, "  the answer  ")

    async def test_use_tool_projects_block_content_to_text(self) -> None:
        """
        Thinking-first block content from the sub-agent comes back as its text,
        honoring the documented str contract instead of leaking a list repr.
        """
        capsule: AgentActivationCapsule = self.make_capsule(ContentFixtures.anthropic_thinking_first())
        result: str = await capsule.use_tool("sub_agent", {"arg": "value"}, {})
        self.assertIsInstance(result, str)
        self.assertEqual(result, "the answer")

    async def test_use_tool_requires_factory_and_spec(self) -> None:
        """
        A capsule created without a factory or parent spec cannot call tools
        and says so, rather than failing deep inside the call.
        """
        capsule: AgentActivationCapsule = AgentActivationCapsule(parent_run_context=MagicMock())
        with self.assertRaises(ValueError):
            await capsule.use_tool("sub_agent", {}, {})

    async def test_use_tool_closes_sub_agent_after_call(self) -> None:
        """
        Each sub-agent is closed right after its call, not deferred to the
        capsule's own close_of_work(), so a CodedTool calling agents in a loop
        does not accumulate open LLM clients.
        """
        capsule: AgentActivationCapsule = self.make_capsule(AIMessage(content="the answer"))
        callable_activation: MagicMock = capsule.factory.create_agent_activation.return_value

        await capsule.use_tool("sub_agent", {}, {})
        callable_activation.close_of_work.assert_awaited_once()

        # The capsule's own close must not close the sub-agent a second time.
        await capsule.close_of_work()
        callable_activation.close_of_work.assert_awaited_once()

    async def test_use_tool_closes_sub_agent_on_failure(self) -> None:
        """
        A sub-agent whose build() raises is still closed before the exception propagates.
        """
        capsule: AgentActivationCapsule = self.make_capsule(AIMessage(content="unused"))
        callable_activation: MagicMock = capsule.factory.create_agent_activation.return_value
        callable_activation.build = AsyncMock(side_effect=RuntimeError("boom"))

        with self.assertRaises(RuntimeError):
            await capsule.use_tool("sub_agent", {}, {})
        callable_activation.close_of_work.assert_awaited_once()

    async def test_use_tool_returns_result_when_close_fails(self) -> None:
        """
        A sub-agent whose close_of_work() raises does not replace the tool's result;
        the failure is logged once instead.
        """
        capsule: AgentActivationCapsule = self.make_capsule(AIMessage(content="the answer"))
        callable_activation: MagicMock = capsule.factory.create_agent_activation.return_value
        callable_activation.close_of_work = AsyncMock(side_effect=RuntimeError("boom"))

        capsule.sensitive_logger = MagicMock()
        result: str = await capsule.use_tool("sub_agent", {}, {})

        self.assertEqual(result, "the answer")
        callable_activation.close_of_work.assert_awaited_once()
        capsule.sensitive_logger.error.assert_called_once()

    async def test_close_of_work_closes_remaining_lingerers_after_failure(self) -> None:
        """
        A lingerer whose close_of_work() raises does not keep the others from being closed.
        """
        capsule: AgentActivationCapsule = AgentActivationCapsule(parent_run_context=MagicMock())
        failing: MagicMock = MagicMock()
        failing.close_of_work = AsyncMock(side_effect=RuntimeError("boom"))
        healthy: MagicMock = MagicMock()
        healthy.close_of_work = AsyncMock()
        capsule.lingerers.append(failing)
        capsule.lingerers.append(healthy)

        capsule.sensitive_logger = MagicMock()
        await capsule.close_of_work()
        capsule.sensitive_logger.error.assert_called_once()

        failing.close_of_work.assert_awaited_once()
        healthy.close_of_work.assert_awaited_once()

    async def test_close_of_work_twice_closes_lingerers_once(self) -> None:
        """
        Calling close_of_work() a second time does not close the same resources again.
        """
        capsule: AgentActivationCapsule = AgentActivationCapsule(parent_run_context=MagicMock())
        lingerer: MagicMock = MagicMock()
        lingerer.close_of_work = AsyncMock()
        capsule.lingerers.append(lingerer)

        await capsule.close_of_work()
        await capsule.close_of_work()

        lingerer.close_of_work.assert_awaited_once()

    async def test_use_reservation_calls_use_tool_with_reservation_id(self) -> None:
        """
        use_reservation() delegates to use_tool() with "/<reservation_id>" as the tool name,
        passes args and sly_data through, and returns use_tool()'s result.
        """
        reservation: MagicMock = MagicMock()
        reservation.get_reservation_id = MagicMock(return_value="copy_cat-1234")

        capsule: AgentActivationCapsule = self.make_capsule(AIMessage(content="unused"))
        capsule.use_tool = AsyncMock(return_value="the answer")

        args: Dict[str, Any] = {"arg": "value"}
        sly_data: Dict[str, Any] = {"secret": "shh"}
        result: str = await capsule.use_reservation(reservation, args, sly_data)

        capsule.use_tool.assert_awaited_once_with("/copy_cat-1234", args, sly_data)
        self.assertEqual(result, "the answer")

    async def test_create_session_returns_factory_session(self) -> None:
        """
        create_session() asks the invocation context's session factory for the agent
        with the effective invocation and returns the session it creates.
        """
        session: MagicMock = MagicMock()
        capsule: AgentActivationCapsule = self.make_session_capsule(session)
        invocation_context: MagicMock = capsule.parent_run_context.get_invocation_context.return_value
        session_factory: MagicMock = invocation_context.get_async_session_factory.return_value

        result: Any = await capsule.create_session("/copy_cat")

        self.assertIs(result, session)
        session_factory.async_create_session.assert_awaited_once_with("/copy_cat", invocation_context, "chatbot")
        session.close.assert_not_called()

    async def test_close_of_work_closes_created_sessions_once(self) -> None:
        """
        Sessions from create_session() are owned by the capsule: close_of_work()
        closes each one, and a second close_of_work() does not close them again.
        """
        session: MagicMock = MagicMock()
        capsule: AgentActivationCapsule = self.make_session_capsule(session)
        await capsule.create_session("/copy_cat")

        await capsule.close_of_work()
        await capsule.close_of_work()

        session.close.assert_called_once()

    async def test_close_of_work_closes_remaining_sessions_after_failure(self) -> None:
        """
        A session whose close() raises does not keep the others from being closed.
        """
        capsule: AgentActivationCapsule = AgentActivationCapsule(parent_run_context=MagicMock())
        failing: MagicMock = MagicMock()
        failing.close = MagicMock(side_effect=RuntimeError("boom"))
        healthy: MagicMock = MagicMock()
        capsule.sessions.append(failing)
        capsule.sessions.append(healthy)

        capsule.sensitive_logger = MagicMock()
        await capsule.close_of_work()
        capsule.sensitive_logger.error.assert_called_once()

        failing.close.assert_called_once()
        healthy.close.assert_called_once()

    async def test_create_session_rejects_non_external_name(self) -> None:
        """
        A bare in-network agent name is rejected before the session factory is consulted.
        """
        capsule: AgentActivationCapsule = self.make_session_capsule(MagicMock())
        invocation_context: MagicMock = capsule.parent_run_context.get_invocation_context.return_value
        session_factory: MagicMock = invocation_context.get_async_session_factory.return_value

        with self.assertRaises(ValueError):
            await capsule.create_session("copy_cat")
        session_factory.async_create_session.assert_not_awaited()

    async def test_create_session_raises_when_factory_returns_none(self) -> None:
        """
        A factory that cannot create a session is reported, not returned as None.
        """
        capsule: AgentActivationCapsule = self.make_session_capsule(None)

        with self.assertRaises(ValueError):
            await capsule.create_session("/copy_cat")
        self.assertEqual(capsule.sessions, [])
