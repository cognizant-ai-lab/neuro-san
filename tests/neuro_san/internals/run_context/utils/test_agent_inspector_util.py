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
from neuro_san.internals.run_context.utils.agent_inspector_util import AgentInspectorUtil


class TestAgentInspectorUtil(TestCase):
    """
    Unit tests for AgentInspectorUtil.get_llm_config_sly_data_schema().
    """

    NETWORK_NAME: str = "byok_network"

    LLM_CONFIG_SCHEMA: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "openai_api_key": {"type": "string", "description": "The user's OpenAI API key"}
        },
    }

    def make_agent_network(self, front_man_function: Dict[str, Any]) -> AgentNetwork:
        """
        Builds an AgentNetwork whose front man has the given function block, plus one helper agent.

        :param front_man_function: The function block of the front man
        :return: An AgentNetwork named NETWORK_NAME
        """
        config: Dict[str, Any] = {
            "tools": [
                {"name": "front", "function": front_man_function},
                {"name": "helper", "function": {"description": "y"}},
            ]
        }
        return AgentNetwork(config, self.NETWORK_NAME)

    def test_returns_llm_config_schema(self) -> None:
        """
        The llm_config property of the front man's sly_data_schema is returned.
        """
        front_man_function: Dict[str, Any] = {
            "description": "x",
            "sly_data_schema": {
                "type": "object",
                "properties": {
                    "llm_config": self.LLM_CONFIG_SCHEMA,
                    "other": {"type": "string"},
                },
                "required": ["llm_config"],
            },
        }
        agent_network: AgentNetwork = self.make_agent_network(front_man_function)

        result: Dict[str, Any] = AgentInspectorUtil.get_llm_config_sly_data_schema(agent_network)

        self.assertEqual(self.LLM_CONFIG_SCHEMA, result)

    def test_no_llm_config_in_sly_data_schema(self) -> None:
        """
        A sly_data_schema without an llm_config property yields None.
        """
        front_man_function: Dict[str, Any] = {
            "description": "x",
            "sly_data_schema": {
                "type": "object",
                "properties": {"other": {"type": "string"}},
            },
        }
        agent_network: AgentNetwork = self.make_agent_network(front_man_function)

        self.assertIsNone(AgentInspectorUtil.get_llm_config_sly_data_schema(agent_network))

    def test_no_sly_data_schema(self) -> None:
        """
        A front man without a sly_data_schema yields None.
        """
        agent_network: AgentNetwork = self.make_agent_network({"description": "x"})

        self.assertIsNone(AgentInspectorUtil.get_llm_config_sly_data_schema(agent_network))

    def test_no_inspector(self) -> None:
        """
        A None inspector yields None.
        """
        self.assertIsNone(AgentInspectorUtil.get_llm_config_sly_data_schema(None))
