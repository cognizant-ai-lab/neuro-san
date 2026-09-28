
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
from neuro_san.internals.graph.registry.agent_tool_registry import AgentToolRegistry


class TestAgentToolRegistry(TestCase):
    """
    Unit tests for AgentToolRegistry as the AgentNetworkInspector that agents
    actually see at run time: what it answers about the network it wraps.
    """

    NETWORK_NAME: str = "deep/math_guy"

    def make_registry(self) -> AgentToolRegistry:
        """
        Builds a registry around a minimal AgentNetwork with a single front man.

        :return: An AgentToolRegistry wrapping a network named NETWORK_NAME.
        """
        config: Dict[str, Any] = {
            "tools": [
                {"name": "front", "function": {"description": "x"}}
            ]
        }
        agent_network: AgentNetwork = AgentNetwork(config, self.NETWORK_NAME)
        return AgentToolRegistry(agent_network)

    def test_get_network_name_comes_from_the_wrapped_network(self) -> None:
        """
        The registry reports the wrapped network's name, so a tool factory asking
        its inspector where a problem lives gets the manifest name of the network.
        """
        registry: AgentToolRegistry = self.make_registry()
        self.assertEqual(registry.get_network_name(), self.NETWORK_NAME)
