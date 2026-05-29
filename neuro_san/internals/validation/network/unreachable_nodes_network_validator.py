
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
from typing import Set

from logging import getLogger
from logging import Logger

from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class UnreachableNodesNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator that looks for topological issues in an agent network.
    Specifically, unreachable nodes or issues with number of front men.
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

        self.logger.info("Validating agent network structure...")

        # Find front man agents
        front_man_agents: Set[str] = self.find_all_front_man_agents(name_to_spec)

        if len(front_man_agents) == 0:
            errors.append("No front man agent found in network")
        elif len(front_man_agents) > 1:
            errors.append(f"Multiple front man agents found: {sorted(front_man_agents)}. Expected exactly one.")

        # Find unreachable agents (only meaningful if we have exactly one front man agent)
        unreachable_agents: Set[str] = set()
        if len(front_man_agents) == 1:
            front_man_agent: str = next(iter(front_man_agents))
            unreachable_agents = self.find_unreachable_agents(name_to_spec, front_man_agent)
            if unreachable_agents:
                errors.append(f"Unreachable agents found: {sorted(unreachable_agents)}")

        if len(errors) > 0:
            # Only warn if there is a problem
            self.logger.warning(str(errors))

        return errors

    def get_agent_down_chains(self, agent_spec: Dict[str, Any]) -> List[str]:
        """
        Build the list of traversable down-chain agent names for an agent spec.

        Down-chains come from two sources: the traditional `tools` field (a list of agent
        names and/or inline dicts), and `args.tools` (the convention for coded tools, which
        may be a dict of label -> agent name or a list of names). Both are read through
        the inherited coerce helpers so a malformed value (the #852 case where `tools`
        is a string) is treated as empty instead of crashing on `str + list`. The shape
        error itself is surfaced by ToolsShapeValidator running in the validation chain.

        Dict-shaped entries (MCP/inline tool configs) and URL/path entries are filtered
        out so the result contains only the agent names that this validator should
        traverse.

        :param agent_spec: The agent specification dictionary
        :return: List of agent-name strings reachable from this spec.
        """
        raw_down_chains: List[Any] = self.coerce_tools(agent_spec) + self.coerce_args_tools(agent_spec)
        safe_down_chains: List[str] = self.remove_dictionary_tools(raw_down_chains)

        traversable_down_chains: List[str] = []
        for tool in safe_down_chains:
            if not self.is_url_or_path(tool):
                traversable_down_chains.append(tool)
        return traversable_down_chains

    def find_all_front_man_agents(self, name_to_spec: Dict[str, Any]) -> Set[str]:
        """
        Find all front man agents - agents that have down-chains but are not down-chains of others.

        :param name_to_spec: The agent network to validate
        :return: Set of front man agent names
        """
        all_down_chains: Set[str] = set()
        has_down_chains: Set[str] = set()

        for agent_name, agent_config in name_to_spec.items():
            down_chains: List[str] = self.get_agent_down_chains(agent_config)
            if down_chains:
                has_down_chains.add(agent_name)
                all_down_chains.update(down_chains)

        # Potential front man agents are agents that have down-chains but are not down-chains of others
        front_man_agents: Set[str] = has_down_chains - all_down_chains

        # Special case: If there's only one agent in the network, it's always a front man agent
        if len(front_man_agents) == 0 and len(name_to_spec) == 1:
            # It's OK to have a single front man agent with no down-chains
            one_front_man: str = list(name_to_spec.keys())[0]
            front_man_agents.add(one_front_man)

        return front_man_agents

    def find_unreachable_agents(self, name_to_spec: Dict[str, Any], front_man_agent: str) -> Set[str]:
        """
        Find agents that are unreachable from the front man agent using Depth-First Search (DFS) traversal.

        :param name_to_spec: The agent network to validate
        :param front_man_agent: The single front man agent to start from
        :return: Set of unreachable agent names
        """
        # Step 1: Initialize set to track all agents we can reach from front man agent
        reachable_agents: Set[str] = set()

        # Step 2: Initialize visited set to track DFS traversal (prevents infinite loops in cycles)
        visited: Set[str] = set()

        # Step 3: Start DFS traversal from the front man agent to find all reachable agents
        self.dfs_reachability_traversal(name_to_spec, front_man_agent, visited, reachable_agents)

        # Step 4: Get complete set of all agents in the network
        all_agents: Set[str] = set(name_to_spec.keys())

        # Step 5: Calculate unreachable agents by subtracting reachable from all agents
        unreachable_agents: Set[str] = all_agents - reachable_agents

        # Step 6: Return the set of agents that cannot be reached from front man agent
        return unreachable_agents

    def dfs_reachability_traversal(self, name_to_spec: Dict[str, Any], agent: str,
                                   visited: Set[str], reachable_agents: Set[str]):
        """
        Perform DFS traversal to find all agents reachable from a specific starting agent.

        :param name_to_spec: The agent network to validate
        :param agent: Current agent being visited
        :param visited: Set of agents already visited in this traversal (prevents infinite loops)
        :param reachable_agents: Set to collect all agents that can be reached
        """
        # Step 1: Check if we've already visited this agent or if it doesn't exist in network
        if agent in visited or agent not in name_to_spec:
            return  # Skip already visited agents or non-existent agents

        # Step 2: Mark current agent as visited to prevent revisiting
        visited.add(agent)

        # Step 3: Add current agent to our reachable set
        reachable_agents.add(agent)

        # Step 4: Get all child agents (down_chains) of current agent
        empty: Dict[str, Any] = {}
        agent_spec: Dict[str, Any] = name_to_spec.get(agent, empty)
        down_chains: List[str] = self.get_agent_down_chains(agent_spec)

        # Step 5: Recursively visit each child agent to continue the traversal
        for child_agent in down_chains:
            # The recursion will handle visited check and network existence
            self.dfs_reachability_traversal(name_to_spec, child_agent, visited, reachable_agents)
