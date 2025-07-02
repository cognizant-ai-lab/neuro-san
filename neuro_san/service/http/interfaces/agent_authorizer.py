
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
"""
See class comment for details
"""
from neuro_san.service.generic.async_agent_service import AsyncAgentService


class AgentAuthorizer:
    """
    Abstract interface implementing some policy
    of allowing to route incoming requests to an agent.
    """

    def allow(self, agent_name) -> AsyncAgentService:
        """
        :param agent_name: name of an agent
        :return: instance of AsyncAgentService if routing requests is allowed for this agent;
                 None otherwise
        """
        raise NotImplementedError
