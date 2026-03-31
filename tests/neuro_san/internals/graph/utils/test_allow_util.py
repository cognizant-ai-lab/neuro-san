
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
from unittest import TestCase

from neuro_san import REGISTRIES_DIR
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.graph.utils.allow_util import AllowUtil


class TestAllowUtil(TestCase):
    """
    Unit tests for AllowUtil class.
    """

    def get_agent_network(self, hocon_file: str) -> AgentNetwork:
        """
        :param hocon_file: the hocon file to restore
        :return: the AgentNetwork specified by the hocon file within the neuro-san repo registries
        """
        file_reference: str = REGISTRIES_DIR.get_file_in_basis(hocon_file)
        restorer = AgentNetworkRestorer()
        agent_network: AgentNetwork = restorer.restore(file_reference=file_reference)
        return agent_network

    def test_allow_not_there(self):
        """
        Tests when the allow block is not present anywhere
        """
        agent_network: AgentNetwork = self.get_agent_network("hello_world.hocon")
        is_allowed: bool = AllowUtil.is_allowed(agent_network, "reservations", ["middleware"])
        self.assertFalse(is_allowed)

    def test_allow_in_agent(self):
        """
        Tests when the allow block is present in an agent
        """
        agent_network: AgentNetwork = self.get_agent_network("copy_cat.hocon")
        is_allowed: bool = AllowUtil.is_allowed(agent_network, "reservations", ["middleware"])
        self.assertTrue(is_allowed)

    def test_allow_in_middleware(self):
        """
        Tests when the allow block is present in an agent
        """
        agent_network: AgentNetwork = self.get_agent_network("copy_cat_middleware.hocon")
        is_allowed: bool = AllowUtil.is_allowed(agent_network, "reservations", ["middleware"])
        self.assertTrue(is_allowed)
