
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

from asyncio import run
from unittest import TestCase
from unittest.mock import MagicMock

from neuro_san import REGISTRIES_DIR
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.run_context.langchain.toolbox.toolbox_factory import ToolboxFactory
from neuro_san.session.async_direct_agent_session import AsyncDirectAgentSession
from neuro_san.session.direct_agent_session import DirectAgentSession


class TestDirectAgentSessionConnectivity(TestCase):
    """
    Unit tests for the toolbox factory wiring in the connectivity() methods
    of DirectAgentSession and AsyncDirectAgentSession.
    """

    def get_sample_registry(self, hocon_file: str) -> AgentNetwork:
        """
        :param hocon_file: A hocon file reference within this repo
        """
        file_reference = REGISTRIES_DIR.get_file_in_basis(hocon_file)
        restorer = AgentNetworkRestorer()
        agent_network: AgentNetwork = restorer.restore(file_reference=file_reference)
        return agent_network

    def make_toolbox_factory(self) -> ToolboxFactory:
        """
        :return: A ToolboxFactory unaffected by the environment.
        """
        toolbox_factory = ToolboxFactory()
        # Keep the test hermetic: no user toolbox info file from the environment.
        toolbox_factory.toolbox_info_file = None
        return toolbox_factory

    def test_connectivity_uses_injected_toolbox_factory(self):
        """
        Tests that a toolbox factory passed to the sync session constructor
        reaches the ConnectivityReporter and is loaded by reporting.
        """
        agent_network: AgentNetwork = self.get_sample_registry("hello_world.hocon")
        toolbox_factory: ToolboxFactory = self.make_toolbox_factory()
        session = DirectAgentSession(agent_network=agent_network,
                                     invocation_context=None,
                                     toolbox_factory=toolbox_factory)
        self.assertIs(session.toolbox_factory, toolbox_factory)

        response: Dict[str, Any] = session.connectivity({})
        self.assertIn("connectivity_info", response)
        self.assertTrue(toolbox_factory.loaded)

    def test_connectivity_falls_back_to_invocation_context_factory(self):
        """
        Tests that with no factory passed, the sync session uses the
        invocation context's toolbox factory.
        """
        agent_network: AgentNetwork = self.get_sample_registry("hello_world.hocon")
        toolbox_factory: ToolboxFactory = self.make_toolbox_factory()
        invocation_context = MagicMock()
        invocation_context.get_toolbox_factory.return_value = toolbox_factory
        session = DirectAgentSession(agent_network=agent_network,
                                     invocation_context=invocation_context)
        self.assertIs(session.toolbox_factory, toolbox_factory)

        response: Dict[str, Any] = session.connectivity({})
        self.assertIn("connectivity_info", response)
        self.assertTrue(toolbox_factory.loaded)

    def test_async_connectivity_uses_injected_toolbox_factory(self):
        """
        Tests that a toolbox factory passed to the async session constructor
        reaches the ConnectivityReporter and is loaded by reporting.
        """
        agent_network: AgentNetwork = self.get_sample_registry("hello_world.hocon")
        toolbox_factory: ToolboxFactory = self.make_toolbox_factory()
        session = AsyncDirectAgentSession(agent_network=agent_network,
                                          invocation_context=None,
                                          toolbox_factory=toolbox_factory)
        self.assertIs(session.toolbox_factory, toolbox_factory)

        response: Dict[str, Any] = run(session.connectivity({}))
        self.assertIn("connectivity_info", response)
        self.assertTrue(toolbox_factory.loaded)

    def test_async_connectivity_falls_back_to_invocation_context_factory(self):
        """
        Tests that with no factory passed, the async session uses the
        invocation context's toolbox factory.
        """
        agent_network: AgentNetwork = self.get_sample_registry("hello_world.hocon")
        toolbox_factory: ToolboxFactory = self.make_toolbox_factory()
        invocation_context = MagicMock()
        invocation_context.get_toolbox_factory.return_value = toolbox_factory
        session = AsyncDirectAgentSession(agent_network=agent_network,
                                          invocation_context=invocation_context)
        self.assertIs(session.toolbox_factory, toolbox_factory)

        response: Dict[str, Any] = run(session.connectivity({}))
        self.assertIn("connectivity_info", response)
        self.assertTrue(toolbox_factory.loaded)
