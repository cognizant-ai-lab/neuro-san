
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT
from typing import Dict

from leaf_common.time.timeout import Timeout

from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.run_context.factory.master_toolbox_factory import MasterToolboxFactory
from neuro_san.internals.run_context.factory.master_llm_factory import MasterLlmFactory
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.network_providers.service_agent_network_storage import ServiceAgentNetworkStorage
from neuro_san.session.direct_agent_session import DirectAgentSession
from neuro_san.session.external_agent_session_factory import ExternalAgentSessionFactory
from neuro_san.session.missing_agent_check import MissingAgentCheck
from neuro_san.session.session_invocation_context import SessionInvocationContext


class DirectAgentSessionFactory:
    """
    Sets up everything needed to use a DirectAgentSession more as a library.
    This includes:
        * Some reading of AgentNetworks
        * Setting up ServiceAgentNetworkStorage with agent networks
          which were read in
        * Initializing an LlmFactory
    """

    def __init__(self):
        """
        Constructor
        """
        manifest_restorer = RegistryManifestRestorer()
        self.manifest_networks: Dict[str, AgentNetwork] = manifest_restorer.restore()
        network_storage: ServiceAgentNetworkStorage = ServiceAgentNetworkStorage.get_instance()
        for agent_name, agent_network in self.manifest_networks.items():
            network_storage.add_agent_network(agent_name, agent_network)

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

        llm_factory: ContextTypeLlmFactory = MasterLlmFactory.create_llm_factory()
        toolbox_factory: ContextTypeToolboxFactory = MasterToolboxFactory.create_toolbox_factory()
        # Load once now that we know what tool registry to use.
        # Include "agent_llm_info_file" and "agent_toolbox_info_file" from agent network hocon
        # to llm factory and toolbox_factory, respectively.
        agent_llm_info_file: str = agent_network.get_agent_llm_info_file()
        agent_toolbox_info_file: str = agent_network.get_agent_toolbox_info_file()
        llm_factory.load(agent_llm_info_file)
        toolbox_factory.load(agent_toolbox_info_file)

        factory = ExternalAgentSessionFactory(use_direct=use_direct)
        invocation_context = SessionInvocationContext(factory, llm_factory, toolbox_factory, metadata)
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
            network_storage: ServiceAgentNetworkStorage =\
                ServiceAgentNetworkStorage.get_instance()
            agent_network_provider: AgentNetworkProvider =\
                network_storage.get_agent_network_provider(agent_name)
            agent_network = agent_network_provider.get_agent_network()

        # Common place for nice error messages when networks are not found
        MissingAgentCheck.check_agent_network(agent_network, agent_name)

        return agent_network
