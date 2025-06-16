
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

from neuro_san.internals.graph.registry.agent_network import AgentNetwork


class AgentNetworkProvider:
    """
    Abstract interface for providing an AgentNetwork instance at run-time.
    """
    def get_agent_network(self) -> AgentNetwork:
        """
        :return: AgentNetwork instance or None if no such AgentNetwork is available.
        """
        raise NotImplementedError
