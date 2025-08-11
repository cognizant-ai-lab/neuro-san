
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
from typing import List

import logging

from leaf_common.config.config_filter import ConfigFilter


class NameCorrectionConfigFilter(ConfigFilter):
    """
    ConfigFilter implementation for correcting potentially invalid internal
    agent names within a single registry.
    """

    def filter_config(self, basis_config: Dict[str, Any]) \
            -> Dict[str, Any]:
        """
        Filters the given basis config.

        Ideally this would be a Pure Function in that it would not
        modify the caller's arguments so that the caller has a chance
        to decide whether to take any changes returned.

        :param basis_config: The config dictionary to act as the basis
                for filtering
        :return: A config dictionary, potentially modified as per the
                policy encapsulated by the implementation
        """

        if basis_config is None:
            return basis_config

        tools: List[Dict[str, Any]] = basis_config.get("tools")
        if tools is None or len(tools) == 0:
            # Nothing to do. Exit early.
            return basis_config

        corrections: Dict[str, str] = {}
        errors: List[str] = []

        # Loop through all the tools making corrections or logging errors.
        tools = basis_config.get("tools")
        for tool in tools:

            name = tool.get("name")
            new_name = self.validate_name(name)

            if new_name.startswith("Error: "):
                # Add to the errors
                errors.append(new_name)
            elif new_name != name:
                # Make a correction
                tool[name] = new_name
                corrections[name] = new_name

        # Make the name corrections consistent in the tool lists
        for tool in tools:
            agent_tools: List[str] = []
            agent_tools = tool.get("tools", agent_tools)
            if not isinstance(agent_tools, List) or len(agent_tools) == 0:
                # Nothing to correct
                continue

            new_agent_tools: List[str] = []
            for agent_tool in agent_tools:
                if agent_tool in corrections:
                    new_agent_tools.append(corrections.get(agent_tool))
                else:
                    new_agent_tools.append(agent_tool)

            tool["tools"] = new_agent_tools

        # Spit out information about errors
        logger = logging.getLogger(self.__class__.__name__)
        for error in errors:
            logger.error(error)

        # Spit out information about corrections
        for original, correction in corrections.items():
            logger.info("Correcting %s to %s", str(original), str(correction))

        return basis_config

    def validate_name(self, name: str) -> str:
        """
        :param name: The name of an agent/tool as given in the hocon file.
        :return: If the name itself is valid, simply return the input.
                If the given name is invalid, attempt to correct it and return
                a new string.  If it is not correctable, return a string that starts
                with "Error: " that describes the problem..
        """
        if name is None:
            # No name is not correctable
            return "Error: no name for agent/tool"

        if not isinstance(name, str):
            # Non-string names are not correctable
            return f"Error: agent/tool name must be a string {name}"

        if len(name) == 0:
            # An empty name is not correctable
            return "Error: agent/tool name cannot be empty"

        new_name: str = name
        if "/" in new_name:
            # Names may not contain '/'.
            # We reserve this character as part of a URI specification of a hierarchy
            # of agents.
            new_name = new_name.replace("/", "_")

        return new_name
