
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

import os

from unittest import TestCase
from unittest.mock import patch

from neuro_san import REGISTRIES_DIR
from neuro_san.internals.chat.connectivity_reporter import ConnectivityReporter
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.run_context.langchain.toolbox.toolbox_factory import ToolboxFactory


class TestConnectivityReporter(TestCase):
    """
    Unit tests for ConnectivityReporter class.
    """

    def test_assumptions(self):
        """
        Can we construct?
        """
        agent_network: AgentNetwork = None
        reporter = ConnectivityReporter(agent_network)
        self.assertIsNotNone(reporter)

    def get_sample_registry(self, hocon_file: str) -> AgentNetwork:
        """
        :param hocon_file: A hocon file reference within this repo
        """
        file_reference = REGISTRIES_DIR.get_file_in_basis(hocon_file)
        restorer = AgentNetworkRestorer()
        agent_network: AgentNetwork = restorer.restore(file_reference=file_reference)
        return agent_network

    def test_hello_world(self):
        """
        Tests the connectivity of the hello world hocon
        """
        agent_network: AgentNetwork = self.get_sample_registry("hello_world.hocon")

        # The reporter's self-built factory reads AGENT_TOOLBOX_INFO_FILE at
        # construction. Keep the test hermetic against the environment.
        with patch.dict(os.environ):
            os.environ.pop("AGENT_TOOLBOX_INFO_FILE", None)
            reporter = ConnectivityReporter(agent_network)
            messages: List[Dict[str, Any]] = reporter.report_network_connectivity()
        self.assertEqual(len(messages), 2)

        # First guy is the front-man and he only has a single tool
        connectivity: Dict[str, Any] = messages[0]
        self.assertIsNotNone(connectivity)
        self.assertEqual(connectivity.get("display_as"), "llm_agent")

        tools: List[str] = connectivity.get("tools")
        self.assertIsNotNone(tools)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0], "synonymizer")

        # Next guy is the synonymizer and has no tools
        connectivity: Dict[str, Any] = messages[1]
        self.assertIsNotNone(connectivity)
        self.assertEqual(connectivity.get("display_as"), "llm_agent")

        tools: List[str] = connectivity.get("tools")
        self.assertIsNotNone(tools)
        self.assertEqual(len(tools), 0)

    def test_injected_toolbox_factory_is_used(self):
        """
        Tests that a toolbox factory passed to the constructor is used as-is
        rather than being replaced by one built from the inspector's config,
        and that reporting loads it.
        """
        agent_network: AgentNetwork = self.get_sample_registry("hello_world.hocon")
        toolbox_factory = ToolboxFactory()
        # Keep the test hermetic: no user toolbox info file from the environment.
        toolbox_factory.toolbox_info_file = None
        reporter = ConnectivityReporter(agent_network, toolbox_factory)
        self.assertIs(reporter.toolbox_factory, toolbox_factory)

        messages: List[Dict[str, Any]] = reporter.report_network_connectivity()
        self.assertEqual(len(messages), 2)
        self.assertTrue(toolbox_factory.loaded)

    def test_injected_toolbox_factory_data_is_consulted(self):
        """
        Tests that display_as information comes from the injected factory's
        toolbox infos, not from a factory built behind the scenes.
        """
        agent_network: AgentNetwork = self.get_sample_registry("date_time_timezone.hocon")
        toolbox_factory = ToolboxFactory()
        # Keep the test hermetic: no user toolbox info file from the environment.
        toolbox_factory.toolbox_info_file = None
        # Seed distinctive tool info and mark loaded so load() keeps it as-is.
        # A self-built or bundled factory would report "coded_tool" instead.
        toolbox_factory.toolbox_infos = {
            "get_current_date_time": {
                "class": "mock_package.mock_module.MockTool",
                "display_as": "injected_tool",
            }
        }
        toolbox_factory.loaded = True

        reporter = ConnectivityReporter(agent_network, toolbox_factory)
        messages: List[Dict[str, Any]] = reporter.report_network_connectivity()

        display_as_by_origin: Dict[str, str] = {
            message.get("origin"): message.get("display_as") for message in messages
        }
        self.assertEqual(display_as_by_origin.get("current_date_time"), "injected_tool")

    def test_assemble_tool_list_args_tools_dict(self):
        """
        Tests that an agent referencing downstream agents via `args.tools`
        as a dict (the coded-tool convention) has those references included
        in the assembled tool list. Previously the dict.values() result was
        a dict_values view that failed the isinstance(args_tools, List)
        check, silently dropping all coded-tool down-chains.
        """
        agent_spec: Dict[str, Any] = {
            "args": {"tools": {"helper": "agent_a", "fallback": "agent_b"}},
        }
        tools: List[str] = ConnectivityReporter.assemble_tool_list(agent_spec)
        self.assertEqual(sorted(tools), ["agent_a", "agent_b"])

    def test_assemble_tool_list_tools_as_string_does_not_iterate_chars(self):
        """
        Tests that a malformed `tools` field (string instead of list) does
        not silently iterate the string character-by-character. coerce_tools
        treats it as empty.
        """
        agent_spec: Dict[str, Any] = {"tools": "agent_a"}
        tools: List[str] = ConnectivityReporter.assemble_tool_list(agent_spec)
        self.assertEqual([], tools)

    def test_assemble_tool_list_dict_element_does_not_crash(self):
        """
        Tests that a dict element in `tools` (e.g., an inline MCP server
        config) is filtered out instead of raising TypeError: unhashable
        type: 'dict' when added to the dedup set. Other string entries are
        retained.
        """
        agent_spec: Dict[str, Any] = {
            "tools": ["agent_a", {"server": "mcp_server"}, "agent_b"],
        }
        tools: List[str] = ConnectivityReporter.assemble_tool_list(agent_spec)
        self.assertEqual(tools, ["agent_a", "agent_b"])
