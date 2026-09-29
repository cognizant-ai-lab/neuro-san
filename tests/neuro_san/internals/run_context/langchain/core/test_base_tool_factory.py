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
from typing import Union

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
    Test cases for BaseToolFactory: which creator each kind of tool reference
    is dispatched to, and the record of exposed names kept across kinds.

    The policy of each kind lives with its creator in the tools package and
    is tested there.
    """

    MCP_ADAPTER_PATH: str = "neuro_san.internals.run_context.langchain.tools.mcp_tool_creator.LangChainMcpAdapter"
    EXTERNAL_ADAPTER_PATH: str = ("neuro_san.internals.run_context.langchain.tools.external_agent_tool_creator."
                                  "ExternalToolAdapter")
    AGENT_LOCATION: str = "agent 'researcher' of agent network 'deep/math_guy'"
    FUNCTION_JSON: Dict[str, Any] = {
        "description": "Answers questions.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to answer."}
            },
            "required": ["question"]
        }
    }

    @override
    def setUp(self) -> None:
        """
        The collaborators make_factory() mocks are kept on the test so the
        tests can assert against them.
        """
        self.tool_caller: MagicMock = None
        self.invocation_context: MagicMock = None
        self.journal: MagicMock = None

    @staticmethod
    def make_named_tool(name: str) -> MagicMock:
        """
        Builds a StructuredTool-shaped mock with the given name.

        :param name: The exposed tool name
        :return: A StructuredTool-shaped mock carrying that name
        """
        tool = MagicMock(spec=StructuredTool)
        tool.name = name
        return tool

    def make_factory(self, agent_spec: Dict[str, Any] = None, tool_from_toolbox: Any = None) -> BaseToolFactory:
        """
        Builds a factory with mocked collaborators, kept on self for assertions.

        :param agent_spec: What the inspector reports for any name; None means the
                           name is not in the network, so it is treated as external
        :param tool_from_toolbox: What the toolbox factory should return
        :return: The BaseToolFactory
        """
        inspector = MagicMock()
        inspector.get_agent_tool_spec = MagicMock(return_value=agent_spec)
        inspector.get_network_name = MagicMock(return_value="deep/math_guy")

        self.tool_caller = MagicMock()
        self.tool_caller.get_inspector = MagicMock(return_value=inspector)
        self.tool_caller.get_name = MagicMock(return_value="researcher")
        self.tool_caller.get_sly_data = MagicMock(return_value={})

        toolbox_factory = MagicMock()
        toolbox_factory.create_tool_from_toolbox = MagicMock(return_value=tool_from_toolbox)
        self.invocation_context = MagicMock()
        self.invocation_context.get_toolbox_factory = MagicMock(return_value=toolbox_factory)

        self.journal = MagicMock()
        self.journal.write_message = AsyncMock()

        return BaseToolFactory(self.tool_caller, self.invocation_context, self.journal)

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

        self.assertEqual(factory.agent_location, self.AGENT_LOCATION)

    async def test_internal_agent_with_function_becomes_a_function_tool(self) -> None:
        """
        A name the inspector knows, whose spec has a "function", becomes a
        function tool named after it, and the name is recorded as exposed.
        """
        factory: BaseToolFactory = self.make_factory(agent_spec={"function": self.FUNCTION_JSON})

        tool: Union[BaseTool, List[BaseTool]] = await factory.create_base_tool("helper")

        self.assertIsInstance(tool, BaseTool)
        self.assertEqual(tool.name, "helper")
        self.assertEqual(factory.exposed_tool_names.get_names(), {"helper"})

    async def test_internal_agent_with_toolbox_goes_to_the_toolbox(self) -> None:
        """
        A spec naming a "toolbox" entry is handed to the toolbox creator with
        the agent's args and name.
        """
        predefined: MagicMock = self.make_named_tool("searcher")
        factory: BaseToolFactory = self.make_factory(agent_spec={"toolbox": "web_search", "args": {"depth": 2}},
                                                     tool_from_toolbox=predefined)

        tool: Union[BaseTool, List[BaseTool]] = await factory.create_base_tool("searcher")

        self.assertIs(tool, predefined)
        toolbox_factory = self.invocation_context.get_toolbox_factory()
        toolbox_factory.create_tool_from_toolbox.assert_called_once_with("web_search", {"depth": 2}, "searcher")

    async def test_internal_agent_without_function_or_toolbox_is_none(self) -> None:
        """
        A spec with neither "function" nor "toolbox" yields no tool and exposes no name.
        """
        factory: BaseToolFactory = self.make_factory(agent_spec={"instructions": "Just think."})

        tool: Union[BaseTool, List[BaseTool]] = await factory.create_base_tool("thinker")

        self.assertIsNone(tool)
        self.assertEqual(factory.exposed_tool_names.get_names(), set())

    async def test_unknown_plain_name_is_none(self) -> None:
        """
        A name the inspector does not know, that is neither an external agent
        nor an MCP reference, yields no tool.
        """
        factory: BaseToolFactory = self.make_factory(agent_spec=None)

        tool: Union[BaseTool, List[BaseTool]] = await factory.create_base_tool("nobody")

        self.assertIsNone(tool)
        self.journal.write_message.assert_not_awaited()

    async def test_non_string_reference_raises_type_error(self) -> None:
        """
        A tool reference must be a string or an MCP dictionary; anything else is
        a TypeError at the dispatch point.
        """
        factory: BaseToolFactory = self.make_factory(agent_spec=None)

        with self.assertRaises(TypeError):
            await factory.create_external_tool(42)

    @patch(EXTERNAL_ADAPTER_PATH)
    async def test_external_agent_reference_goes_to_the_external_creator(self, mock_adapter_class: MagicMock) -> None:
        """
        A "/name" reference the inspector does not know is an external agent:
        its reported function becomes the tool, under the safe agent name.

        :param mock_adapter_class: Patched ExternalToolAdapter class.
        """
        mock_adapter: MagicMock = mock_adapter_class.return_value
        mock_adapter.get_function_json = AsyncMock(return_value=self.FUNCTION_JSON)
        factory: BaseToolFactory = self.make_factory(agent_spec=None)

        tool: Union[BaseTool, List[BaseTool]] = await factory.create_base_tool("/network_b")

        self.assertIsInstance(tool, BaseTool)
        self.assertEqual(tool.name, ExternalAgentParsing.get_safe_agent_name("/network_b"))
        self.assertEqual(factory.exposed_tool_names.get_names(), {tool.name})

    @patch(MCP_ADAPTER_PATH)
    async def test_mcp_reference_goes_to_the_mcp_creator(self, mock_adapter_class: MagicMock) -> None:
        """
        An MCP URL the inspector does not know is handed to the MCP creator, and
        every tool it returns is recorded as exposed.

        :param mock_adapter_class: Patched LangChainMcpAdapter class.
        """
        mock_adapter: MagicMock = mock_adapter_class.return_value
        mock_adapter.get_unmatched_allowed_tools = MagicMock(return_value=[])
        mock_adapter.get_mcp_tools = AsyncMock(return_value=[self.make_named_tool("a"), self.make_named_tool("b")])
        factory: BaseToolFactory = self.make_factory(agent_spec=None)

        tools: Union[BaseTool, List[BaseTool]] = await factory.create_base_tool("https://mcp.example.com/mcp")

        self.assertEqual(len(tools), 2)
        self.assertEqual(factory.exposed_tool_names.get_names(), {"a", "b"})
        mock_adapter_class.assert_called_once_with(self.AGENT_LOCATION)

    @patch(MCP_ADAPTER_PATH)
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
        factory: BaseToolFactory = self.make_factory(agent_spec=None)

        first: List[BaseTool] = await factory.create_base_tool("https://one.example.com/mcp")
        second: List[BaseTool] = await factory.create_base_tool("https://two.example.com/mcp")

        self.assertEqual(first, [first_server_tool])
        self.assertEqual(second, [other_tool])
        self.assertEqual(factory.exposed_tool_names.get_names(), {"a__b", "other_tool"})
        self.journal.write_message.assert_awaited_once()
        reported: AgentMessage = self.journal.write_message.await_args.args[0]
        expected_start: str = f"{self.AGENT_LOCATION}: MCP tool 'a__b' from https://two.example.com/mcp"
        self.assertTrue(reported.content.startswith(expected_start), reported.content)
        self.assertIn("skipping it", reported.content)
