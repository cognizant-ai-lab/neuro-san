
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


class AgentNameMapper:
    """
    An abstract policy defining conversion
    between agent name as specified in a manifest file
    and a file path (relative to registry root directory) to this agent definition file.
    """

    def agent_name_to_filepath(self, agent_name: str) -> str:
        """
        Converts an agent name from manifest file to file path to this agent definition file.
        """
        raise NotImplementedError()

    def filepath_to_agent_network_name(self, filepath: str) -> str:
        """
        Converts a file path to agent definition file (relative to registry root directory)
        to agent network name identifying it to the service.
        """
        raise NotImplementedError()
