
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

from os import environ

from neuro_san.internals.graph.registry.agent_network import AgentNetwork


class MissingAgentCheck:
    """
    Convience and consolidation for checks against missing/misnamed agents.
    """

    @staticmethod
    def check_agent_network(agent_network: AgentNetwork, agent_name: str) -> AgentNetwork:
        """
        :param agent_network: The AgentNetwork to check
        :param agent_name: The name of the agent to use for the session.
        :return: The AgentNetwork corresponding to the agent_name
        """

        if agent_network is None:
            message = f"""
Agent named "{agent_name}" not found in manifest file: {environ.get("AGENT_MANIFEST_FILE")}.

Some things to check:
1. If the manifest file named above is None, know that the default points
   to the one provided with the neuro-san library for a smoother out-of-box
   experience.  If the agent you wanted is not part of that standard distribution,
   you need to set the AGENT_MANIFEST_FILE environment variable to point to a
   manifest.hocon file associated with your own project(s).
2. Check that the environment variable AGENT_MANIFEST_FILE is pointing to
   the manifest.hocon file that you expect and has no typos.
3. Does your manifest.hocon file contain a key for the agent specified?
4. Does the value for the key in the manifest file have a value of 'true'?
5. Does your agent name have a typo either in the hocon file or on the command line?
"""
            raise ValueError(message)

        return agent_network
