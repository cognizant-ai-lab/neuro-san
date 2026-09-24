
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

from unittest import TestCase

from neuro_san.internals.graph.registry.agent_network import AgentNetwork


class TestAgentNetwork(TestCase):
    """
    Unit tests for AgentNetwork, focused on the MCP tool naming state:
    how a network is marked as an MCP tool, which name it advertises,
    and how that marking is withdrawn.
    """

    # A nested registry path, the case where the network name and the
    # provider-safe tool name differ.
    NETWORK_NAME: str = "deep/math_guy"
    SAFE_TOOL_NAME: str = "deep__math_guy"

    def make_agent_network(self) -> AgentNetwork:
        """
        Builds a minimal AgentNetwork with a single front man.

        :return: An AgentNetwork named NETWORK_NAME that is not (yet) an MCP tool.
        """
        config: Dict[str, Any] = {
            "tools": [
                {"name": "front", "function": {"description": "x"}}
            ]
        }
        return AgentNetwork(config, self.NETWORK_NAME)

    def test_not_mcp_tool_by_default(self) -> None:
        """
        A freshly constructed network is not an MCP tool and has no tool name.
        """
        agent_network: AgentNetwork = self.make_agent_network()
        self.assertFalse(agent_network.is_mcp_tool())
        self.assertIsNone(agent_network.get_mcp_tool_name())

    def test_set_as_mcp_tool_defaults_to_network_name(self) -> None:
        """
        Calling set_as_mcp_tool() with no argument keeps the historical behavior:
        the tool is advertised under the network name itself.
        """
        agent_network: AgentNetwork = self.make_agent_network()
        agent_network.set_as_mcp_tool()
        self.assertTrue(agent_network.is_mcp_tool())
        self.assertEqual(self.NETWORK_NAME, agent_network.get_mcp_tool_name())

    def test_set_as_mcp_tool_with_explicit_name(self) -> None:
        """
        An explicit tool name is advertised while the network name stays the internal key.
        """
        agent_network: AgentNetwork = self.make_agent_network()
        agent_network.set_as_mcp_tool(self.SAFE_TOOL_NAME)
        self.assertTrue(agent_network.is_mcp_tool())
        self.assertEqual(self.SAFE_TOOL_NAME, agent_network.get_mcp_tool_name())
        self.assertEqual(self.NETWORK_NAME, agent_network.get_network_name())

    def test_set_as_mcp_tool_empty_name_falls_back_to_network_name(self) -> None:
        """
        An empty tool name is not usable, so the network name is used instead.
        """
        agent_network: AgentNetwork = self.make_agent_network()
        agent_network.set_as_mcp_tool("")
        self.assertTrue(agent_network.is_mcp_tool())
        self.assertEqual(self.NETWORK_NAME, agent_network.get_mcp_tool_name())

    def test_set_as_mcp_tool_twice_takes_latest_name(self) -> None:
        """
        Re-marking a network replaces the advertised name rather than keeping the first one.
        """
        agent_network: AgentNetwork = self.make_agent_network()
        agent_network.set_as_mcp_tool("first")
        agent_network.set_as_mcp_tool("second")
        self.assertEqual("second", agent_network.get_mcp_tool_name())

    def test_clear_mcp_tool(self) -> None:
        """
        clear_mcp_tool() withdraws the MCP marking and forgets the tool name.
        """
        agent_network: AgentNetwork = self.make_agent_network()
        agent_network.set_as_mcp_tool(self.SAFE_TOOL_NAME)
        agent_network.clear_mcp_tool()
        self.assertFalse(agent_network.is_mcp_tool())
        self.assertIsNone(agent_network.get_mcp_tool_name())
        # The network itself is untouched; only the MCP exposure is gone.
        self.assertEqual(self.NETWORK_NAME, agent_network.get_network_name())

    def test_clear_mcp_tool_when_not_mcp_tool_is_harmless(self) -> None:
        """
        Clearing a network that was never an MCP tool leaves it in the same non-MCP state.
        """
        agent_network: AgentNetwork = self.make_agent_network()
        agent_network.clear_mcp_tool()
        self.assertFalse(agent_network.is_mcp_tool())
        self.assertIsNone(agent_network.get_mcp_tool_name())
