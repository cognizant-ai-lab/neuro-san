
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
from typing import List

from unittest import TestCase

from neuro_san import REGISTRIES_DIR
from neuro_san.internals.graph.persistence.agent_network_on_boarding import AgentNetworkOnBoarding
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork


class TestAgentNetworkOnBoarding(TestCase):
    """
    Unit tests for AgentNetworkOnBoarding class.
    """

    # deep/math_guy.hocon has the AGENT_TOOL_PATH-relative class reference "calculator.Calculator".
    RELATIVE_NETWORK: str = "deep/math_guy.hocon"

    @staticmethod
    def restore(file_reference: str) -> AgentNetwork:
        """
        Load an agent network from the registry.

        :param file_reference: The registry-relative hocon file
        :return: The restored AgentNetwork
        """
        restorer = AgentNetworkRestorer()
        hocon_file: str = REGISTRIES_DIR.get_file_in_basis(file_reference)
        agent_network: AgentNetwork = restorer.restore(file_reference=hocon_file)
        return agent_network

    def test_relative_class_allowed_by_default(self):
        """
        Tests that an AGENT_TOOL_PATH-relative class reference passes on-boarding by default
        """
        on_boarding: AgentNetworkOnBoarding = AgentNetworkOnBoarding()
        agent_network: AgentNetwork = self.restore(self.RELATIVE_NETWORK)

        errors: List[str] = on_boarding.validate(agent_network.get_config())
        self.assertEqual(0, len(errors), errors)
        self.assertIsNotNone(on_boarding.on_board(agent_network))

    def test_relative_class_rejected_when_fully_qualified_required(self):
        """
        Tests that an AGENT_TOOL_PATH-relative class reference fails on-boarding when fully-qualified
        classes are required
        """
        on_boarding: AgentNetworkOnBoarding = AgentNetworkOnBoarding(require_fully_qualified_classes=True)
        agent_network: AgentNetwork = self.restore(self.RELATIVE_NETWORK)

        errors: List[str] = on_boarding.validate(agent_network.get_config())
        self.assertEqual(1, len(errors))
        self.assertIn("calculator.Calculator", errors[0])
        self.assertIsNone(on_boarding.on_board(agent_network))

    def test_fully_qualified_class_accepted_when_required(self):
        """
        Tests that a fully-qualified class reference passes on-boarding when fully-qualified
        classes are required
        """
        on_boarding: AgentNetworkOnBoarding = AgentNetworkOnBoarding(require_fully_qualified_classes=True)
        agent_network: AgentNetwork = self.restore("math_guy_fully_qualified.hocon")

        errors: List[str] = on_boarding.validate(agent_network.get_config())
        self.assertEqual(0, len(errors), errors)
        self.assertIsNotNone(on_boarding.on_board(agent_network))
