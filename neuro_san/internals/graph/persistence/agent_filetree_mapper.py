
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
from pathlib import Path

from neuro_san.internals.interfaces.agent_name_mapper import AgentNameMapper


class AgentFileTreeMapper(AgentNameMapper):
    """
    A simple policy implementation defining conversion
    between agent name as specified in a manifest file
    and a file path (relative to registry root directory) to this agent definition file.
    """

    def agent_name_to_filepath(self, agent_name: str) -> str:
        """
        Converts an agent name from registry manifest to file path to this agent definition file.
        """
        return agent_name

    def filepath_to_agent_network_name(self, filepath: str) -> str:
        """
        Converts a file path to agent definition file (relative to registry root directory)
        to agent network name identifying it to the service.
        """
        # Remove file name extension, leave everything else in place.
        return str(Path(filepath).with_suffix(""))
