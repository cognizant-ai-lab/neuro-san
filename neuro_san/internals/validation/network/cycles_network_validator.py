
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
from neuro_san.internals.validation.network.graph_visitation_state import GraphVisitationState


class CyclesNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator that looks for cycles in the agent graph.
    This is not strictly forbidden by neuro-san infrastructure, but there
    are some situtations where it is good to at least flag it.
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

        # Find cyclical agents
        cyclical_agents: Set[str] = self.find_cyclical_agents(name_to_spec)
        if cyclical_agents:
            errors.append(f"Cyclical dependencies found in agents: {sorted(cyclical_agents)}")

        if len(errors) > 0:
            # Only warn if there is a problem
            self.logger.warning(str(errors))

        return errors

    def find_cyclical_agents(self, name_to_spec: Dict[str, Any]) -> Set[str]:
        """
        Find agents that are part of cyclical dependencies using DFS.

        :param name_to_spec: The agent network to validate
        :return: Set of agent names that are part of cycles
        """
        # Step 1: Initialize state tracking for all agents
        state: Dict[str, GraphVisitationState] = {}
        for agent in name_to_spec.keys():
            state[agent] = GraphVisitationState.UNVISITED

        # Step 2: Set to collect all agents that are part of cycles
        cyclical_agents: Set[str] = set()

        # Step 3: Start DFS from each unvisited agent to ensure we check all components
        # (the network might have disconnected parts)
        for agent in name_to_spec.keys():
            if state[agent] == GraphVisitationState.UNVISITED:  # Only start DFS from unvisited agents
                # Start DFS with empty path - this agent is the root of this search
                self.dfs_cycle_detection(name_to_spec, agent, [], state, cyclical_agents)

        # Step 4: Return all agents that were found to be part of cycles
        return cyclical_agents

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def dfs_cycle_detection(self, name_to_spec: Dict[str, Any], agent: str,
                            path: List[str], state: Dict[str, GraphVisitationState],
                            cyclical_agents: Set[str]):
        """
        Perform Depth-First Search (DFS) traversal to detect cycles starting from a specific agent.

        :param name_to_spec: The agent network to validate
        :param agent: Current agent being visited
        :param path: Current path from start to current agent (for cycle identification)
        :param state: Dictionary tracking visit state of all agents
        :param cyclical_agents: Set to collect all agents that are part of any cycle
        """
        # Step 1: Check if we've encountered an agent currently being processed (back edge = cycle)
        if state[agent] == GraphVisitationState.CURRENTLY_BEING_PROCESSED:
            # Cycle detected! The agent is already in our current processing path
            cycle_start_idx: int = path.index(agent)  # Find where the cycle starts in our path
            cycle_agents: Set[str] = set(path[cycle_start_idx:] + [agent])  # Extract all agents in the cycle
            cyclical_agents.update(cycle_agents)  # Add them to our result set
            return

        # Step 2: Skip if this agent was already fully processed in a previous DFS
        if state[agent] == GraphVisitationState.FULLY_PROCESSED:
            return  # Already completed, no need to process again

        # Step 3: Mark agent as currently being processed (prevents infinite recursion)
        state[agent] = GraphVisitationState.CURRENTLY_BEING_PROCESSED

        # Step 4: Add current agent to the path (to track the route we took to get here)
        path.append(agent)

        # Step 5: Get all child agents (down_chains) of current agent
        # coerce_tools treats a malformed `tools` (non-list) as empty so this
        # validator does not iterate the characters of a string. The shape
        # error itself is reported separately by ToolsShapeValidator.
        agent_spec: Dict[str, Any] = name_to_spec.get(agent, {})
        down_chains: List[Any] = self.coerce_tools(agent_spec)
        safe_down_chains: List[str] = self.remove_dictionary_tools(down_chains)

        # Step 6: Recursively visit each child agent
        for child_agent in safe_down_chains:
            # Only visit child if it exists in our network (safety check)
            if child_agent in name_to_spec:
                self.dfs_cycle_detection(name_to_spec, child_agent, path, state, cyclical_agents)

        # Step 7: Backtrack - remove current agent from path as we're done processing it
        path.pop()

        # Step 8: Mark agent as fully processed (all its descendants have been explored)
        state[agent] = GraphVisitationState.FULLY_PROCESSED
