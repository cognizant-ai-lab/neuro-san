
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

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class UnreachableNodesNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator that looks for topological issues in an agent network.
    Specifically, unreachable nodes or issues with number of front men.
    """

    def __init__(self, network_name: str = None):
        """
        Constructor

        :param network_name: The agent network name for diagnostic log lines
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.network_name: str = network_name

    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        Validate the agent network, specifically in the form of a name -> agent spec dictionary.

        :param name_to_spec: The name -> agent spec dictionary to validate
        :return: A list of error messages
        """
        errors: List[str] = []

        self.logger.debug("Validating %s agent network structure...", self.network_name)

        # Find top agents
        top_agents: Set[str] = self.find_all_top_agents(name_to_spec)

        if len(top_agents) == 0:
            errors.append("No top agent found in network")
        elif len(top_agents) > 1:
            errors.append(f"Multiple top agents found: {sorted(top_agents)}. Expected exactly one.")

        # Find unreachable agents (only meaningful if we have exactly one top agent)
        unreachable_agents: Set[str] = set()
        if len(top_agents) == 1:
            top_agent: str = next(iter(top_agents))
            unreachable_agents = self.find_unreachable_agents(name_to_spec, top_agent)
            if unreachable_agents:
                errors.append(f"Unreachable agents found: {sorted(unreachable_agents)}")

        if len(errors) > 0:
            # Only warn if there is a problem
            self.logger.warning(str(errors))

        return errors

    def find_all_top_agents(self, name_to_spec: Dict[str, Any]) -> Set[str]:
        """
        Find all top agents - agents that have down-chains but are not down-chains of others.

        :param name_to_spec: The agent network to validate
        :return: Set of top agent names
        """
        all_down_chains: Set[str] = set()
        has_down_chains: Set[str] = set()

        for agent_name, agent_config in name_to_spec.items():
            down_chains: List[str] = agent_config.get("tools", [])
            if down_chains:

                has_down_chains.add(agent_name)

                safe_down_chains: List[str] = self.remove_dictionary_tools(down_chains)
                all_down_chains.update(safe_down_chains)

        # Potential top agents are agents that have down-chains but are not down-chains of others
        top_agents: Set[str] = has_down_chains - all_down_chains

        # Special case: If there's only one agent in the network, it's always a top agent
        if len(top_agents) == 0 and len(name_to_spec) == 1:
            # It's OK to have a single top agent with no down-chains
            one_top: str = list(name_to_spec.keys())[0]
            top_agents.add(one_top)

        return top_agents

    def find_unreachable_agents(self, name_to_spec: Dict[str, Any], top_agent: str) -> Set[str]:
        """
        Find agents that are unreachable from the top agent using Depth-First Search (DFS) traversal.

        :param name_to_spec: The agent network to validate
        :param top_agent: The single top agent to start from
        :return: Set of unreachable agent names
        """
        # Step 1: Initialize set to track all agents we can reach from top agent
        reachable_agents: Set[str] = set()

        # Step 2: Initialize visited set to track DFS traversal (prevents infinite loops in cycles)
        visited: Set[str] = set()

        # Step 3: Start DFS traversal from the top agent to find all reachable agents
        self.dfs_reachability_traversal(name_to_spec, top_agent, visited, reachable_agents)

        # Step 4: Get complete set of all agents in the network
        all_agents: Set[str] = set(name_to_spec.keys())

        # Step 5: Calculate unreachable agents by subtracting reachable from all agents
        unreachable_agents: Set[str] = all_agents - reachable_agents

        # Step 6: Return the set of agents that cannot be reached from top agent
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
        no_tools: List[str] = []

        agent_spec: Dict[str, Any] = name_to_spec.get(agent, empty)
        extractor = DictionaryExtractor(agent_spec)

        traditional_down_chains: List[str] = extractor.get("tools", no_tools)
        coded_tool_down_chains: List[str] = list(extractor.get("args.tools", empty).values())
        down_chains: List[str] = traditional_down_chains + coded_tool_down_chains
        safe_down_chains: List[str] = self.remove_dictionary_tools(down_chains)

        # Step 5: Recursively visit each child agent to continue the traversal
        for child_agent in safe_down_chains:
            # Skip URL/path tools - they're not agents
            if not self.is_url_or_path(child_agent):
                # Visit each child - the recursion will handle visited check and network existence
                self.dfs_reachability_traversal(name_to_spec, child_agent, visited, reachable_agents)
