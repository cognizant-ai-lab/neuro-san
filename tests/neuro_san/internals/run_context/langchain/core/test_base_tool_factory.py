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
from unittest.mock import patch

from typing_extensions import override

from langchain_core.tools import BaseTool
from langchain_core.tools import StructuredTool

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.graph.registry.agent_tool_registry import AgentToolRegistry
from neuro_san.internals.run_context.langchain.core.base_tool_factory import BaseToolFactory
from neuro_san.internals.utils.external_agent_parsing import ExternalAgentParsing
from neuro_san.message.types.agent_message import AgentMessage


class TestBaseToolFactory(IsolatedAsyncioTestCase):
    """
    Test cases for BaseToolFactory.

    The cases here currently center on how external agents are presented as
    tools - in particular the default "inquiry" parameter synthesized for a
    front-man that declares no parameters of its own (issue #1228).
    See BaseToolFactory.ensure_external_parameters() for the full rationale.
    """

    EXTERNAL_AGENT_NAME: str = "/network_b"

    @override
    def setUp(self) -> None:
        """
        The synthesis warning is deduplicated per-process via a class-level
        set. Clear it before each test so tests stay order-independent.
        """
        BaseToolFactory.synthesis_warned.clear()

    @override
    def tearDown(self) -> None:
        """
        Clear the per-process synthesis warning set again so a test that
        triggered the warning leaves nothing behind for later modules.
        """
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

    async def test_external_tool_without_parameters_gets_default_schema(self) -> None:
        """
        An external front-man with no function.parameters must be presented
        to the calling LLM with the synthesized required "inquiry" parameter,
        not as a zero-argument tool.
        """
        factory: BaseToolFactory = self.make_factory({"description": "Answers music questions."})

        tool: BaseTool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNotNone(tool)
        self.assertEqual(tool.parameters, BaseToolFactory.DEFAULT_EXTERNAL_PARAMETERS)

        # The args_schema is what actually reaches the calling LLM.
        param_name: str = BaseToolFactory.DEFAULT_EXTERNAL_PARAMETER_NAME
        fields = tool.args_schema.model_fields
        self.assertEqual(list(fields.keys()), [param_name])
        # is_required() is the pydantic v2 FieldInfo API; the v1 models this
        # converter used to build exposed a .required attribute instead.
        self.assertIs(fields[param_name].is_required(), True)

        # The substitution must not be silent.
        factory.journal.write_message.assert_awaited_once()

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
        factory: BaseToolFactory = self.make_factory({
            "description": "Answers music questions.",
            "parameters": declared_parameters
        })

        tool: BaseTool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNotNone(tool)
        self.assertEqual(tool.parameters, declared_parameters)
        self.assertEqual(list(tool.args_schema.model_fields.keys()), ["question"])
        factory.journal.write_message.assert_not_awaited()

    def test_create_function_tool_does_not_mutate_function_json(self) -> None:
        """
        Creating a tool must not add its lookup name to the caller-owned
        function specification.
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
        factory: BaseToolFactory = self.make_factory(function_json)

        tool: BaseTool = factory.create_function_tool(function_json, self.EXTERNAL_AGENT_NAME)

        self.assertEqual(function_json, expected)
        self.assertEqual(tool.name, ExternalAgentParsing.get_safe_agent_name(self.EXTERNAL_AGENT_NAME))

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
        factory: BaseToolFactory = self.make_factory(function_json)

        tool: BaseTool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        self.assertEqual(function_json, expected)
        self.assertEqual(tool.name, ExternalAgentParsing.get_safe_agent_name(self.EXTERNAL_AGENT_NAME))

    async def test_external_tool_with_empty_properties_gets_default_schema(self) -> None:
        """
        A parameters block whose properties dictionary is empty is just as
        uncallable as no parameters at all, so it gets the same substitution.
        """
        factory: BaseToolFactory = self.make_factory({
            "description": "Answers music questions.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        })

        tool: BaseTool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNotNone(tool)
        self.assertEqual(tool.parameters, BaseToolFactory.DEFAULT_EXTERNAL_PARAMETERS)
        factory.journal.write_message.assert_awaited_once()

    async def test_external_tool_without_description_is_not_synthesized(self) -> None:
        """
        A front-man spec with no description fails validation no matter what
        parameters it has (e.g. a hocon with no "function" block at all, for
        which the server reports {}). No synthesis message may be journaled
        for it - the client would see a promise that the request will get
        through, immediately followed by the tool being dropped.
        """
        factory: BaseToolFactory = self.make_factory({})

        tool: BaseTool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNone(tool)

        # Only the validation-failure report, never the synthesis message,
        # and under the invalid-definition banner rather than "unreachable" -
        # the agent did respond.
        factory.journal.write_message.assert_awaited_once()
        reported: AgentMessage = factory.journal.write_message.await_args.args[0]
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

        first_factory: BaseToolFactory = self.make_factory(parameterless)
        first_tool: BaseTool = await first_factory.create_external_tool(self.EXTERNAL_AGENT_NAME)
        self.assertEqual(first_tool.parameters, BaseToolFactory.DEFAULT_EXTERNAL_PARAMETERS)
        first_factory.journal.write_message.assert_awaited_once()

        second_factory: BaseToolFactory = self.make_factory(parameterless)
        second_tool: BaseTool = await second_factory.create_external_tool(self.EXTERNAL_AGENT_NAME)
        self.assertEqual(second_tool.parameters, BaseToolFactory.DEFAULT_EXTERNAL_PARAMETERS)
        second_factory.journal.write_message.assert_not_awaited()

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

        broken_factory: BaseToolFactory = self.make_factory(parameterless)
        await broken_factory.create_external_tool(self.EXTERNAL_AGENT_NAME)
        broken_factory.journal.write_message.assert_awaited_once()

        fixed_factory: BaseToolFactory = self.make_factory(declared)
        await fixed_factory.create_external_tool(self.EXTERNAL_AGENT_NAME)
        fixed_factory.journal.write_message.assert_not_awaited()

        regressed_factory: BaseToolFactory = self.make_factory(parameterless)
        await regressed_factory.create_external_tool(self.EXTERNAL_AGENT_NAME)
        regressed_factory.journal.write_message.assert_awaited_once()

    async def test_unsupported_schema_dialect_is_not_replaced(self) -> None:
        """
        A declared parameters schema in an unsupported JSON Schema dialect
        (no properties, but e.g. additionalProperties) is a declared contract,
        not an absent one. It must be rejected as invalid - never silently
        replaced with the synthesized default.
        """
        factory: BaseToolFactory = self.make_factory({
            "description": "Answers music questions.",
            "parameters": {
                "type": "object",
                "additionalProperties": {"type": "string"}
            }
        })

        tool: BaseTool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNone(tool)
        factory.journal.write_message.assert_awaited_once()
        reported: AgentMessage = factory.journal.write_message.await_args.args[0]
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
                # Each case used to be its own test with a fresh warning set;
                # keep that isolation so no case depends on an earlier one.
                BaseToolFactory.synthesis_warned.clear()
                factory: BaseToolFactory = self.make_factory({
                    "description": "Answers music questions.",
                    "parameters": bad_parameters
                })

                tool: BaseTool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

                self.assertIsNone(tool)
                factory.journal.write_message.assert_awaited_once()
                reported: AgentMessage = factory.journal.write_message.await_args.args[0]
                self.assertIn("invalid function definition", str(reported.content))

    async def test_unreachable_external_tool_reported_as_unreachable(self) -> None:
        """
        A transport-level failure fetching the external agent's function spec
        is a connectivity problem and must keep the "unreachable" banner.
        """
        factory: BaseToolFactory = self.make_factory({})
        session = factory.invocation_context.get_async_session_factory().create_session()
        session.function = AsyncMock(side_effect=ValueError("connection refused"))

        tool: BaseTool = await factory.create_external_tool(self.EXTERNAL_AGENT_NAME)

        self.assertIsNone(tool)
        factory.journal.write_message.assert_awaited_once()
        reported: AgentMessage = factory.journal.write_message.await_args.args[0]
        self.assertIn("unreachable", str(reported.content))
        self.assertNotIn("invalid function definition", str(reported.content))

    async def test_ensure_external_parameters_passes_none_through(self) -> None:
        """
        An unreachable external agent has no function_json at all.
        That case is reported elsewhere and must pass through untouched.
        """
        factory: BaseToolFactory = self.make_factory({})

        result: Dict[str, Any] = await factory.ensure_external_parameters(None, self.EXTERNAL_AGENT_NAME)

        self.assertIsNone(result)
        factory.journal.write_message.assert_not_awaited()

    @staticmethod
    def make_mcp_factory() -> BaseToolFactory:
        """
        :return: A BaseToolFactory whose inspector knows no local agents (so every
                 name is treated as external) and whose sly_data carries no headers
        """
        inspector = MagicMock()
        inspector.get_agent_tool_spec = MagicMock(return_value=None)
        inspector.get_network_name = MagicMock(return_value="deep/math_guy")

        tool_caller = MagicMock()
        tool_caller.get_inspector = MagicMock(return_value=inspector)
        tool_caller.get_name = MagicMock(return_value="researcher")
        tool_caller.get_sly_data = MagicMock(return_value={})

        journal = MagicMock()
        journal.write_message = AsyncMock()

        return BaseToolFactory(tool_caller, MagicMock(), journal)

    @staticmethod
    def make_named_tool(name: str) -> MagicMock:
        """
        :param name: The exposed tool name
        :return: A StructuredTool-shaped mock carrying that name
        """
        tool = MagicMock(spec=StructuredTool)
        tool.name = name
        return tool

    @patch("neuro_san.internals.run_context.langchain.core.base_tool_factory.LangChainMcpAdapter")
    async def test_mcp_tool_repeating_an_exposed_name_is_skipped(self, mock_adapter_class: MagicMock) -> None:
        """
        The adapter resolves collisions within one server only. When a second
        server exposes a name the first already took ("a/b" renamed to "a__b"
        on one, a literal "a__b" on the other), the factory keeps the first and
        skips the second with a journal message, leaving unrelated tools alone.

        :param mock_adapter_class: Patched LangChainMcpAdapter class.
        """
        first_server_tool: MagicMock = self.make_named_tool("a__b")
        second_server_tool: MagicMock = self.make_named_tool("a__b")
        other_tool: MagicMock = self.make_named_tool("other_tool")
        mock_adapter: MagicMock = mock_adapter_class.return_value
        mock_adapter.get_unmatched_allowed_tools = MagicMock(return_value=[])
        mock_adapter.get_mcp_tools = AsyncMock(side_effect=[[first_server_tool], [second_server_tool, other_tool]])
        factory: BaseToolFactory = self.make_mcp_factory()

        first: List[BaseTool] = await factory.create_base_tool("https://one.example.com/mcp")
        second: List[BaseTool] = await factory.create_base_tool("https://two.example.com/mcp")

        self.assertEqual(first, [first_server_tool])
        self.assertEqual(second, [other_tool])
        self.assertEqual(factory.exposed_tool_names, {"a__b", "other_tool"})
        factory.journal.write_message.assert_awaited_once()
        reported: AgentMessage = factory.journal.write_message.await_args.args[0]
        agent_location: str = "agent 'researcher' of agent network 'deep/math_guy'"
        expected_start: str = f"{agent_location}: MCP tool 'a__b' from https://two.example.com/mcp"
        self.assertTrue(reported.content.startswith(expected_start), reported.content)
        self.assertIn("skipping it", reported.content)
        self.assertIn("hocon file", reported.content)
        # The adapter is told the same agent location, so its own warnings can start with it.
        for adapter_call in mock_adapter_class.call_args_list:
            self.assertEqual(adapter_call.args, (agent_location,))

    async def test_non_mcp_tool_repeating_an_exposed_name_is_reported_but_kept(self) -> None:
        """
        A coded or internal tool that repeats an exposed name is reported in the
        journal but not dropped, since dropping it would change behaviour that
        predates the name check.
        """
        factory: BaseToolFactory = self.make_mcp_factory()
        # pylint: disable=protected-access
        await factory._remember_tool_names(self.make_named_tool("search"))
        await factory._remember_tool_names([self.make_named_tool("search"), self.make_named_tool("lookup")])

        self.assertEqual(factory.exposed_tool_names, {"search", "lookup"})
        factory.journal.write_message.assert_awaited_once()
        reported: AgentMessage = factory.journal.write_message.await_args.args[0]
        expected_start: str = ("agent 'researcher' of agent network 'deep/math_guy': "
                               "tool 'search' has the same name as another tool")
        self.assertTrue(reported.content.startswith(expected_start), reported.content)
        self.assertIn("hocon file", reported.content)

    def test_agent_location_is_built_from_the_real_inspector(self) -> None:
        """
        At run time the inspector is an AgentToolRegistry, not an AgentNetwork,
        so the factory must be able to ask it for the network name. A mocked
        inspector would not catch a method missing from the registry.
        """
        config: Dict[str, Any] = {
            "tools": [
                {"name": "researcher", "function": {"description": "x"}}
            ]
        }
        registry: AgentToolRegistry = AgentToolRegistry(AgentNetwork(config, "deep/math_guy"))
        tool_caller = MagicMock()
        tool_caller.get_inspector = MagicMock(return_value=registry)
        tool_caller.get_name = MagicMock(return_value="researcher")
        tool_caller.get_sly_data = MagicMock(return_value={})

        factory: BaseToolFactory = BaseToolFactory(tool_caller, MagicMock(), MagicMock())

        self.assertEqual(factory.agent_location, "agent 'researcher' of agent network 'deep/math_guy'")
