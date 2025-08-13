
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
from typing import Any
from typing import Dict
from typing import List

from copy import copy

from neuro_san.internals.run_context.utils.external_agent_parsing import ExternalAgentParsing


class Origination:
    """
    An instance for common code and state that manipulates and keeps track of origin information
    on a per-AgentSession basis.

    A full origin description is a List of Dictionaries indicating the origin of a chat message.
    An origin can be considered a path to the original call to the front-man.
    Origin dictionaries themselves each have the following keys:
        "tool"                  The string name of the tool in the spec
        "instantiation_index"   An integer indicating which incarnation
                                of the tool is being dealt with.
    """

    INSTANTIATION_START: int = 1
    NUM_INSTANTIATION_INDEX_DIGITS: int = 2

    def __init__(self):
        """
        Constructor
        """
        self.tool_to_index_map: Dict[str, int] = {}

    def add_spec_name_to_origin(self, origin: List[Dict[str, Any]], agent_name: str) \
            -> List[Dict[str, Any]]:
        """
        Adds a single component origin dictionary to the given origin list.
        :param origin: A new List of origin dictionaries indicating the origin of the run.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
        :param agent_name: The agent name to be added to the list.
        :return: The new origin with the agent name at the end of the list
        """
        new_origin: List[Dict[str, Any]] = []

        # Add the name from the spec to the origin, if we have it.
        if origin is None or agent_name is None:
            return new_origin

        # Make a shallow copy of the list, as we are going to modify it
        # and don't want to muck with the original
        new_origin = copy(origin)

        # Find the current instantiation index for the tool
        # and increment it in the map for later use
        instantiation_index: int = self.tool_to_index_map.get(agent_name, Origination.INSTANTIATION_START)
        self.tool_to_index_map[agent_name] = instantiation_index + 1

        # Prepare the origin dictionary to append
        origin_dict: Dict[str, Any] = {
            "tool": agent_name,
            "instantiation_index": instantiation_index
        }
        new_origin.append(origin_dict)

        return new_origin

    @staticmethod
    def get_full_name_from_origin(origin: List[Dict[str, Any]]) -> str:
        """
        :param origin: A List of origin dictionaries indicating the origin of the run.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
        :return: A single string name given an origin path/list
        """
        if origin is None:
            return None

        # Connect all the elements of the origin by the delimiter "."
        origin_list: List[str] = []
        for origin_dict in origin:

            # Get basic fields from the dict
            instantiation_index: int = origin_dict.get("instantiation_index", Origination.INSTANTIATION_START)
            tool: str = origin_dict.get("tool")
            if tool is None:
                # No information of value will be conveyed with no tool set in the dict.
                raise ValueError("tool name in origin_dict is None")

            # Figure out how we will deal with the index
            index_str: str = ""
            if instantiation_index > Origination.INSTANTIATION_START:
                # zfill() adds leading 0's up to the number of characters provided
                index_str = f"-{str(instantiation_index).zfill(Origination.NUM_INSTANTIATION_INDEX_DIGITS)}"

            safe_tool: str = ExternalAgentParsing.get_safe_agent_name(tool)

            # Figure out the single origin string
            origin_str: str = f"{safe_tool}{index_str}"
            origin_list.append(origin_str)

        full_path: str = ".".join(origin_list)

        # Simple replacement of local external agents.
        # DEF - need better recognition of external agent
        full_path = full_path.replace("./", "/")

        return full_path

    def reset(self):
        """
        Resets the origination tracking
        """
        self.tool_to_index_map = {}
