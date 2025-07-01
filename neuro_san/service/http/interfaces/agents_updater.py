
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
from typing import Any
from typing import Dict


class AgentsUpdater:
    """
    Abstract interface for updating current collection of agents
    being served.
    """

    def update_agents(self, metadata: Dict[str, Any]):
        """
        Update list of agents for which serving is allowed.
        :param metadata: metadata to be used for logging if necessary.
        :return: nothing
        """
        raise NotImplementedError
