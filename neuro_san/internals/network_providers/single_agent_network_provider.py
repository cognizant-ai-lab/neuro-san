
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

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider


class SingleAgentNetworkProvider(AgentNetworkProvider):
    """
    Class providing current AgentNetwork for a given agent in the service scope.
    """
    def __init__(self, agent_name: str, agents_table: Dict[str, AgentNetwork]):
        """
        Constructor.
        :param agent_name: name of an agent to provide AgentNetwork instances for;
        :param agents_table: service-wide table mapping agent names to their
            currently active AgentNetwork instances.
            This table is assumed to be dynamically modified outside a single agent scope.
        """
        self.agent_name = agent_name
        self.agents_table: Dict[str, AgentNetwork] = agents_table

    def get_agent_network(self) -> AgentNetwork:
        """
        :return: Current AgentNetwork instance for specific agent name.
                None if this does not exist for the instance's agent_name.
        """
        return self.agents_table.get(self.agent_name)
