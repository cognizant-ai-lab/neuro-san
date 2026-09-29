
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
from typing import List

from copy import deepcopy

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from typing_extensions import override

from langchain_core.tools import BaseTool

from neuro_san.internals.run_context.langchain.tools.external_agent_tool_creator import ExternalAgentToolCreator
from neuro_san.internals.utils.external_agent_parsing import ExternalAgentParsing
from neuro_san.message.types.agent_message import AgentMessage


class TestExternalAgentToolCreator(IsolatedAsyncioTestCase):
    """
    Unit tests for ExternalAgentToolCreator.

    The cases center on how external agents are presented as tools, in
    particular the default "inquiry" parameter synthesized for a front-man
    that declares no parameters of its own (issue #1228).
    See ExternalAgentToolCreator.ensure_external_parameters() for the rationale.
    """

    EXTERNAL_AGENT_NAME: str = "/network_b"
    AGENT_LOCATION: str = "agent 'researcher' of agent network 'deep/math_guy'"

    @override
    def setUp(self) -> None:
        """
        The synthesis warning is deduplicated per-process via a class-level
        set. Clear it before each test so tests stay order-independent.
        """
        ExternalAgentToolCreator.synthesis_warned.clear()

    @override
    def tearDown(self) -> None:
        """
        Clear the per-process synthesis warning set again so a test that
        triggered the warning leaves nothing behind for later modules.
        """
        ExternalAgentToolCreator.synthesis_warned.clear()

    def make_creator(self, function_json: Dict[str, Any]) -> ExternalAgentToolCreator:
        """
        Builds a creator whose mocked external agent reports the given function spec.

        :param function_json: The function spec the mocked external agent reports
        :return: An ExternalAgentToolCreator whose external session plumbing is mocked out
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

        return ExternalAgentToolCreator(tool_caller, invocation_context, journal, self.AGENT_LOCATION)

    async def test_external_tool_without_parameters_gets_default_schema(self) -> None:
        """
        An external front-man with no function.parameters must be presented
        to the calling LLM with the synthesized required "inquiry" parameter,
        not as a zero-argument tool.
        """
        creator: ExternalAgentToolCreator = self.make_creator({"description": "Answers music questions."})

        tool: BaseTool = await creator.create_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNotNone(tool)
        self.assertEqual(tool.parameters, ExternalAgentToolCreator.DEFAULT_EXTERNAL_PARAMETERS)

        # The args_schema is what actually reaches the calling LLM.
        param_name: str = ExternalAgentToolCreator.DEFAULT_EXTERNAL_PARAMETER_NAME
        fields = tool.args_schema.model_fields
        self.assertEqual(list(fields.keys()), [param_name])
        # is_required() is the pydantic v2 FieldInfo API; the v1 models this
        # converter used to build exposed a .required attribute instead.
        self.assertIs(fields.get(param_name).is_required(), True)

        # The substitution must not be silent.
        creator.journal.write_message.assert_awaited_once()

    async def test_external_tool_with_parameters_is_untouched(self) -> None:
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
        creator: ExternalAgentToolCreator = self.make_creator({
            "description": "Answers music questions.",
            "parameters": declared_parameters
        })

        tool: BaseTool = await creator.create_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNotNone(tool)
        self.assertEqual(tool.parameters, declared_parameters)
        self.assertEqual(list(tool.args_schema.model_fields.keys()), ["question"])
        creator.journal.write_message.assert_not_awaited()

    async def test_external_tool_does_not_mutate_function_json(self) -> None:
        """
        A same-server external agent can return its live registry function
        specification by reference. Creating a tool from it must not mutate it.
        """
        function_json: Dict[str, Any] = {
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
        expected: Dict[str, Any] = deepcopy(function_json)
        creator: ExternalAgentToolCreator = self.make_creator(function_json)

        tool: BaseTool = await creator.create_tool(self.EXTERNAL_AGENT_NAME)

        self.assertEqual(function_json, expected)
        self.assertEqual(tool.name, ExternalAgentParsing.get_safe_agent_name(self.EXTERNAL_AGENT_NAME))

    async def test_external_tool_with_empty_properties_gets_default_schema(self) -> None:
        """
        A parameters block whose properties dictionary is empty is just as
        uncallable as no parameters at all, so it gets the same substitution.
        """
        creator: ExternalAgentToolCreator = self.make_creator({
            "description": "Answers music questions.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        })

        tool: BaseTool = await creator.create_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNotNone(tool)
        self.assertEqual(tool.parameters, ExternalAgentToolCreator.DEFAULT_EXTERNAL_PARAMETERS)
        creator.journal.write_message.assert_awaited_once()

    async def test_external_tool_without_description_is_not_synthesized(self) -> None:
        """
        A front-man spec with no description fails validation no matter what
        parameters it has (e.g. a hocon with no "function" block at all, for
        which the server reports {}). No synthesis message may be journaled
        for it - the client would see a promise that the request will get
        through, immediately followed by the tool being dropped.
        """
        creator: ExternalAgentToolCreator = self.make_creator({})

        tool: BaseTool = await creator.create_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNone(tool)

        # Only the validation-failure report, never the synthesis message,
        # and under the invalid-definition banner rather than "unreachable" -
        # the agent did respond.
        creator.journal.write_message.assert_awaited_once()
        reported: AgentMessage = creator.journal.write_message.await_args.args[0]
        self.assertNotIn("synthesized", str(reported.content))
        self.assertIn("invalid function definition", str(reported.content))
        self.assertNotIn("unreachable", str(reported.content))

    async def test_synthesis_warns_once_per_agent(self) -> None:
        """
        Tool resources are rebuilt on every request, but the synthesis
        warning describes a static config condition - it must be reported
        once per process for a given agent, not once per request.
        The synthesis itself must still happen every time.
        """
        parameterless: Dict[str, Any] = {"description": "Answers music questions."}

        first_creator: ExternalAgentToolCreator = self.make_creator(parameterless)
        first_tool: BaseTool = await first_creator.create_tool(self.EXTERNAL_AGENT_NAME)
        self.assertEqual(first_tool.parameters, ExternalAgentToolCreator.DEFAULT_EXTERNAL_PARAMETERS)
        first_creator.journal.write_message.assert_awaited_once()

        second_creator: ExternalAgentToolCreator = self.make_creator(parameterless)
        second_tool: BaseTool = await second_creator.create_tool(self.EXTERNAL_AGENT_NAME)
        self.assertEqual(second_tool.parameters, ExternalAgentToolCreator.DEFAULT_EXTERNAL_PARAMETERS)
        second_creator.journal.write_message.assert_not_awaited()

    async def test_synthesis_warning_rearms_when_agent_is_fixed(self) -> None:
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

        broken_creator: ExternalAgentToolCreator = self.make_creator(parameterless)
        await broken_creator.create_tool(self.EXTERNAL_AGENT_NAME)
        broken_creator.journal.write_message.assert_awaited_once()

        fixed_creator: ExternalAgentToolCreator = self.make_creator(declared)
        await fixed_creator.create_tool(self.EXTERNAL_AGENT_NAME)
        fixed_creator.journal.write_message.assert_not_awaited()

        regressed_creator: ExternalAgentToolCreator = self.make_creator(parameterless)
        await regressed_creator.create_tool(self.EXTERNAL_AGENT_NAME)
        regressed_creator.journal.write_message.assert_awaited_once()

    async def test_unsupported_schema_dialect_is_not_replaced(self) -> None:
        """
        A declared parameters schema in an unsupported JSON Schema dialect
        (no properties, but e.g. additionalProperties) is a declared contract,
        not an absent one. It must be rejected as invalid - never silently
        replaced with the synthesized default.
        """
        creator: ExternalAgentToolCreator = self.make_creator({
            "description": "Answers music questions.",
            "parameters": {
                "type": "object",
                "additionalProperties": {"type": "string"}
            }
        })

        tool: BaseTool = await creator.create_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNone(tool)
        creator.journal.write_message.assert_awaited_once()
        reported: AgentMessage = creator.journal.write_message.await_args.args[0]
        self.assertIn("invalid function definition", str(reported.content))
        self.assertNotIn("synthesized", str(reported.content))

    async def test_non_dict_parameters_reported_as_invalid(self) -> None:
        """
        A malformed spec whose "parameters" is not a dictionary - truthy or
        falsy - must be reported as an invalid function definition: neither
        crashing the calling agent's resource setup with an AttributeError,
        nor being silently repaired with the synthesized default.
        """
        bad_parameters_cases: List[Any] = ["none", [], "", False, 0]
        for bad_parameters in bad_parameters_cases:
            with self.subTest(bad_parameters=bad_parameters):
                # Each case gets a fresh warning set, so no case depends on an earlier one.
                ExternalAgentToolCreator.synthesis_warned.clear()
                creator: ExternalAgentToolCreator = self.make_creator({
                    "description": "Answers music questions.",
                    "parameters": bad_parameters
                })

                tool: BaseTool = await creator.create_tool(self.EXTERNAL_AGENT_NAME)

                self.assertIsNone(tool)
                creator.journal.write_message.assert_awaited_once()
                reported: AgentMessage = creator.journal.write_message.await_args.args[0]
                self.assertIn("invalid function definition", str(reported.content))

    async def test_unreachable_external_tool_reported_as_unreachable(self) -> None:
        """
        A transport-level failure fetching the external agent's function spec
        is a connectivity problem and must keep the "unreachable" banner.
        """
        creator: ExternalAgentToolCreator = self.make_creator({})
        session = creator.invocation_context.get_async_session_factory().create_session()
        session.function = AsyncMock(side_effect=ValueError("connection refused"))

        tool: BaseTool = await creator.create_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNone(tool)
        creator.journal.write_message.assert_awaited_once()
        reported: AgentMessage = creator.journal.write_message.await_args.args[0]
        self.assertIn("unreachable", str(reported.content))
        self.assertNotIn("invalid function definition", str(reported.content))

    async def test_ensure_external_parameters_passes_none_through(self) -> None:
        """
        An unreachable external agent has no function_json at all.
        That case is reported elsewhere and must pass through untouched.
        """
        creator: ExternalAgentToolCreator = self.make_creator({})

        result: Dict[str, Any] = await creator.ensure_external_parameters(None, self.EXTERNAL_AGENT_NAME)

        self.assertIsNone(result)
        creator.journal.write_message.assert_not_awaited()

    async def test_reference_that_is_not_external_is_none_without_a_session(self) -> None:
        """
        A plain agent name is not an external reference. The creator answers
        None and never opens a session for it.
        """
        creator: ExternalAgentToolCreator = self.make_creator({"description": "x"})

        tool: BaseTool = await creator.create_tool("local_agent")

        self.assertIsNone(tool)
        session_factory = creator.invocation_context.get_async_session_factory()
        session_factory.create_session.assert_not_called()
        creator.journal.write_message.assert_not_awaited()
