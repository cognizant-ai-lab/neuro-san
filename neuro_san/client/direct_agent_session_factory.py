
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

from leaf_common.time.timeout import Timeout
from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool

from neuro_san.client.direct_agent_storage_util import DirectAgentStorageUtil
from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.run_context.factory.master_toolbox_factory import MasterToolboxFactory
from neuro_san.internals.run_context.factory.master_llm_factory import MasterLlmFactory
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.network_providers.expiring_agent_network_storage import ExpiringAgentNetworkStorage
from neuro_san.internals.reservations.direct_agent_reservationist import DirectAgentReservationist
from neuro_san.session.direct_agent_session import DirectAgentSession
from neuro_san.session.external_agent_session_factory import ExternalAgentSessionFactory
from neuro_san.session.missing_agent_check import MissingAgentCheck
from neuro_san.session.session_invocation_context import SessionInvocationContext


class DirectAgentSessionFactory:
    """
    Sets up everything needed to use a DirectAgentSession more as a library.
    This includes:
        * Some reading of AgentNetworks
        * Setting up AgentNetworkStorage with agent networks
          which were read in
        * Initializing an LlmFactory
    """

    def __init__(self):
        """
        Constructor
        """
        # Read the manifest once and pass that into the Util call below.
        manifest_restorer = RegistryManifestRestorer()
        manifest_networks: Dict[str, Dict[str, AgentNetwork]] = manifest_restorer.restore()

        self.network_storage_dict: Dict[str, AgentNetworkStorage] = {
            "temp": ExpiringAgentNetworkStorage()
        }

        for storage_type in ["public", "protected"]:
            storage: AgentNetworkStorage = DirectAgentStorageUtil.create_network_storage(manifest_networks,
                                                                                         storage_type=storage_type)
            self.network_storage_dict[storage_type] = storage

    def create_session(self, agent_name: str, use_direct: bool = False,
                       metadata: Dict[str, str] = None, umbrella_timeout: Timeout = None) -> AgentSession:
        """
        :param agent_name: The name of the agent to use for the session.
                This name can be something in the manifest file (with no file suffix)
                or a specific full-reference to an agent network's hocon file.
        :param use_direct: When True, will use a Direct session for
                    external agents that would reside on the same server.
        :param metadata: A grpc metadata of key/value pairs to be inserted into
                         the header. Default is None. Preferred format is a
                         dictionary of string keys to string values.
        :param umbrella_timeout: A Timeout object to periodically check in loops.
                        Default is None (no timeout).
        """

        agent_network: AgentNetwork = self.get_agent_network(agent_name)
        config: Dict[str, Any] = agent_network.get_config()
        llm_factory: ContextTypeLlmFactory = MasterLlmFactory.create_llm_factory(config)
        toolbox_factory: ContextTypeToolboxFactory = MasterToolboxFactory.create_toolbox_factory(config)
        # Load once now that we know what tool registry to use.
        llm_factory.load()
        toolbox_factory.load()

        factory = ExternalAgentSessionFactory(use_direct=use_direct, network_storage_dict=self.network_storage_dict)
        executors_pool = AsyncioExecutorPool()

        # DEF - We could do max_lifetime here, but waiting until that seems necessary.
        reservationist = DirectAgentReservationist(set([self.network_storage_dict.get("temp")]))
        invocation_context = SessionInvocationContext(agent_name,
                                                      factory,
                                                      executors_pool,
                                                      llm_factory,
                                                      toolbox_factory,
                                                      metadata,
                                                      reservationist)
        invocation_context.start()
        session: DirectAgentSession = DirectAgentSession(agent_network=agent_network,
                                                         invocation_context=invocation_context,
                                                         metadata=metadata,
                                                         umbrella_timeout=umbrella_timeout)
        return session

    def get_agent_network(self, agent_name: str) -> AgentNetwork:
        """
        :param agent_name: The name of the agent whose AgentNetwork we want to get.
                This name can be something in the manifest file (with no file suffix)
                or a specific full-reference to an agent network's hocon file.
        :return: The AgentNetwork corresponding to that agent.
        """

        if agent_name is None or len(agent_name) == 0:
            return None

        agent_network: AgentNetwork = None
        if agent_name.endswith(".hocon") or agent_name.endswith(".json"):
            # We got a specific file name
            restorer = AgentNetworkRestorer()
            agent_network = restorer.restore(file_reference=agent_name)
        else:
            # Use the standard stuff available via the manifest file.
            for storage_type in ["public", "protected"]:
                storage: AgentNetworkStorage = self.network_storage_dict.get(storage_type)
                agent_network_provider: AgentNetworkProvider = storage.get_agent_network_provider(agent_name)
                if agent_network_provider is None:
                    continue
                agent_network = agent_network_provider.get_agent_network()
                if agent_network is not None:
                    break

        # Common place for nice error messages when networks are not found
        MissingAgentCheck.check_agent_network(agent_network, agent_name)

        return agent_network
