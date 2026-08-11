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

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from neuro_san.internals.run_context.langchain.core.base_tool_factory import BaseToolFactory


class TestBaseToolFactory:
    """
    Test cases for BaseToolFactory.

    The cases here currently center on how external agents are presented
    as tools: the tool-call arguments are the only channel through which a
    calling agent passes anything to an external agent network.  An external
    front-man that declares no function.parameters used to be presented to
    the calling LLM as a zero-argument tool, which the LLM would invoke
    with {} - the external network silently never received the caller's
    request (issue #1228).  A default "inquiry" parameter is now
    synthesized for that case.
    """

    EXTERNAL_AGENT_NAME: str = "/network_b"

    @pytest.fixture(autouse=True)
    def clear_synthesis_warned(self):
        """
        The synthesis warning is deduplicated per-process via a class-level
        set. Clear it around each test so tests stay order-independent.
        """
        BaseToolFactory.synthesis_warned.clear()
        yield
        BaseToolFactory.synthesis_warned.clear()

    @staticmethod
    def make_factory(function_json: Dict[str, Any]) -> BaseToolFactory:
        """
        :param function_json: The function spec the mocked external agent reports
        :return: A BaseToolFactory whose external session plumbing is mocked out
        """
        session = MagicMock()
        session.function = AsyncMock(return_value={"function": function_json})

        session_factory = MagicMock()
        session_factory.create_session = MagicMock(return_value=session)

        invocation_context = MagicMock()
        invocation_context.get_async_session_factory = MagicMock(return_value=session_factory)

        journal = MagicMock()
        journal.write_message = AsyncMock()

        tool_caller = MagicMock()

        return BaseToolFactory(tool_caller, invocation_context, journal)

    @pytest.mark.asyncio
    async def test_external_tool_without_parameters_gets_default_schema(self):
        """
        An external front-man with no function.parameters must be presented
        to the calling LLM with the synthesized required "inquiry" parameter,
        not as a zero-argument tool.
        """
        factory = self.make_factory({"description": "Answers music questions."})

        tool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        assert tool is not None
        assert tool.parameters == BaseToolFactory.DEFAULT_EXTERNAL_PARAMETERS

        # The args_schema is what actually reaches the calling LLM.
        param_name: str = BaseToolFactory.DEFAULT_EXTERNAL_PARAMETER_NAME
        fields = tool.args_schema.__fields__
        assert list(fields.keys()) == [param_name]
        assert fields[param_name].required is True

        # The substitution must not be silent.
        factory.journal.write_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_external_tool_with_parameters_is_untouched(self):
        """
        An external front-man that declares its own parameters must be
        passed through exactly as declared, with no warning.
        """
        declared_parameters: Dict[str, Any] = {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to answer."
                }
            },
            "required": ["question"]
        }
        factory = self.make_factory({
            "description": "Answers music questions.",
            "parameters": declared_parameters
        })

        tool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        assert tool is not None
        assert tool.parameters == declared_parameters
        assert list(tool.args_schema.__fields__.keys()) == ["question"]
        factory.journal.write_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_external_tool_with_empty_properties_gets_default_schema(self):
        """
        A parameters block whose properties dictionary is empty is just as
        uncallable as no parameters at all, so it gets the same substitution.
        """
        factory = self.make_factory({
            "description": "Answers music questions.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        })

        tool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        assert tool is not None
        assert tool.parameters == BaseToolFactory.DEFAULT_EXTERNAL_PARAMETERS
        factory.journal.write_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_external_tool_without_description_is_not_synthesized(self):
        """
        A front-man spec with no description fails validation no matter what
        parameters it has (e.g. a hocon with no "function" block at all, for
        which the server reports {}). No synthesis message may be journaled
        for it - the client would see a promise that the request will get
        through, immediately followed by the tool being dropped.
        """
        factory = self.make_factory({})

        tool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        assert tool is None

        # Only the validation-failure report, never the synthesis message,
        # and under the invalid-definition banner rather than "unreachable" -
        # the agent did respond.
        factory.journal.write_message.assert_awaited_once()
        reported = factory.journal.write_message.await_args.args[0]
        assert "synthesized" not in str(reported.content)
        assert "invalid function definition" in str(reported.content)
        assert "unreachable" not in str(reported.content)

    @pytest.mark.asyncio
    async def test_synthesis_warns_once_per_agent(self):
        """
        Tool resources are rebuilt on every request, but the synthesis
        warning describes a static config condition - it must be reported
        once per process for a given agent, not once per request.
        The synthesis itself must still happen every time.
        """
        parameterless: Dict[str, Any] = {"description": "Answers music questions."}

        first_factory = self.make_factory(parameterless)
        first_tool = await first_factory.create_external_tool(self.EXTERNAL_AGENT_NAME)
        assert first_tool.parameters == BaseToolFactory.DEFAULT_EXTERNAL_PARAMETERS
        first_factory.journal.write_message.assert_awaited_once()

        second_factory = self.make_factory(parameterless)
        second_tool = await second_factory.create_external_tool(self.EXTERNAL_AGENT_NAME)
        assert second_tool.parameters == BaseToolFactory.DEFAULT_EXTERNAL_PARAMETERS
        second_factory.journal.write_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_synthesis_warning_rearms_when_agent_is_fixed(self):
        """
        Hocon files can be edited and hot-reloaded without a server restart.
        Observing the agent with declared parameters must re-arm the warning,
        so a later regression back to parameterless warns anew.
        """
        parameterless: Dict[str, Any] = {"description": "Answers music questions."}
        declared: Dict[str, Any] = {
            "description": "Answers music questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to answer."
                    }
                },
                "required": ["question"]
            }
        }

        broken_factory = self.make_factory(parameterless)
        await broken_factory.create_external_tool(self.EXTERNAL_AGENT_NAME)
        broken_factory.journal.write_message.assert_awaited_once()

        fixed_factory = self.make_factory(declared)
        await fixed_factory.create_external_tool(self.EXTERNAL_AGENT_NAME)
        fixed_factory.journal.write_message.assert_not_awaited()

        regressed_factory = self.make_factory(parameterless)
        await regressed_factory.create_external_tool(self.EXTERNAL_AGENT_NAME)
        regressed_factory.journal.write_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unsupported_schema_dialect_is_not_replaced(self):
        """
        A declared parameters schema in an unsupported JSON Schema dialect
        (no properties, but e.g. additionalProperties) is a declared contract,
        not an absent one. It must be rejected as invalid - never silently
        replaced with the synthesized default.
        """
        factory = self.make_factory({
            "description": "Answers music questions.",
            "parameters": {
                "type": "object",
                "additionalProperties": {"type": "string"}
            }
        })

        tool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        assert tool is None
        factory.journal.write_message.assert_awaited_once()
        reported = factory.journal.write_message.await_args.args[0]
        assert "invalid function definition" in str(reported.content)
        assert "synthesized" not in str(reported.content)

    @pytest.mark.asyncio
    async def test_non_dict_parameters_reported_as_invalid(self):
        """
        A malformed spec whose "parameters" is not a dictionary must be
        reported as an invalid function definition, not crash the calling
        agent's resource setup with an AttributeError.
        """
        factory = self.make_factory({
            "description": "Answers music questions.",
            "parameters": "none"
        })

        tool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        assert tool is None
        factory.journal.write_message.assert_awaited_once()
        reported = factory.journal.write_message.await_args.args[0]
        assert "invalid function definition" in str(reported.content)

    @pytest.mark.asyncio
    async def test_unreachable_external_tool_reported_as_unreachable(self):
        """
        A transport-level failure fetching the external agent's function spec
        is a connectivity problem and must keep the "unreachable" banner.
        """
        factory = self.make_factory({})
        session = factory.invocation_context.get_async_session_factory().create_session()
        session.function = AsyncMock(side_effect=ValueError("connection refused"))

        tool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        assert tool is None
        factory.journal.write_message.assert_awaited_once()
        reported = factory.journal.write_message.await_args.args[0]
        assert "unreachable" in str(reported.content)
        assert "invalid function definition" not in str(reported.content)

    @pytest.mark.asyncio
    async def test_ensure_external_parameters_passes_none_through(self):
        """
        An unreachable external agent has no function_json at all.
        That case is reported elsewhere and must pass through untouched.
        """
        factory = self.make_factory({})

        result = await factory.ensure_external_parameters(None, self.EXTERNAL_AGENT_NAME)

        assert result is None
        factory.journal.write_message.assert_not_awaited()
