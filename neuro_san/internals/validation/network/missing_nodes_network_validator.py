
# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT

from typing import Any
from typing import Dict
from typing import List

from logging import getLogger
from logging import Logger

from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class MissingNodesNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator that looks for missing nodes that are referred to
    in an agent network.
    """

    def __init__(self):
        """
        Constructor
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        Validate the agent network, specifically in the form of a name -> agent spec dictionary.

        :param name_to_spec: The name -> agent spec dictionary to validate
        :return: A list of error messages
        """
        errors: List[str] = []

        # Validate that agent tools have corresponding nodes
        missing_nodes: Dict[str, List[str]] = self.find_missing_agent_nodes(name_to_spec)
        if missing_nodes:
            for agent, missing_tools in missing_nodes.items():
                # Format the comma-separated list of missing tools
                tools_str: str = ", ".join(f"'{tool}'" for tool in missing_tools)
                errors.append(
                    f"Agent '{agent}' references non-existent agent(s) in tools: {tools_str}"
                )

        if len(errors) > 0:
            # Only warn if there is a problem
            self.logger.warning(str(errors))

        return errors

    def find_missing_agent_nodes(self, name_to_spec: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Find agents referenced in "tools" lists that don't have corresponding nodes in the network.

        :param name_to_spec: The agent network to validate
        :return: Dictionary mapping agent names to list of tools that reference non-existent agents
                Format: {agent_name: [missing_tool1, missing_tool2, ...]}
        """
        missing_nodes: Dict[str, List[str]] = {}

        # Iterate through all agents in the network
        for agent_name, agent_data in name_to_spec.items():

            # coerce_tools treats a malformed `tools` (non-list) as empty so this
            # validator does not iterate the characters of a string. The shape
            # error itself is reported separately by ToolsShapeValidator.
            tools: List[Any] = self.coerce_tools(agent_data)
            safe_tools: List[str] = self.remove_dictionary_tools(tools)

            # Check each tool in the agent's tools list
            for tool in safe_tools:
                # Skip URL/path tools - they're not agents and don't need nodes
                if self.is_url_or_path(tool):
                    continue

                # If tool is an agent reference but has no node in network, it's invalid
                if tool not in name_to_spec:
                    if agent_name not in missing_nodes:
                        missing_nodes[agent_name] = []
                    missing_nodes[agent_name].append(tool)

        return missing_nodes
