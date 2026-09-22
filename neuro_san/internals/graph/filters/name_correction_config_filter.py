
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

    A corrected name is propagated to every reference other tools hold to it,
    both in their "tools" lists and in their "args.tools" (the coded-tool
    convention for declaring downstream agents), so both ends of each edge agree.
    """

    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Any]:
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
        tool: Dict[str, Any] = None
        for tool in tools:

            name: str = tool.get("name")
            new_name: str = self.validate_name(name)

            if new_name.startswith("Error: "):
                # Add to the errors
                errors.append(new_name)
            elif new_name != name:
                # Make a correction to the tool's own "name" field.  The references other
                # tools hold to it are rewritten below from the corrections table, so both
                # sides of every edge end up using the corrected name.
                tool["name"] = new_name
                corrections[name] = new_name

        # Make the name corrections consistent in the tool lists
        for tool in tools:
            agent_tools: List[str] = []
            agent_tools = tool.get("tools", agent_tools)
            # This is an if rather than a continue on purpose: a coded tool typically has
            # no "tools" list at all, yet still needs its args.tools rewritten below.
            if isinstance(agent_tools, list) and len(agent_tools) > 0:
                new_agent_tools: List[str] = []
                for agent_tool in agent_tools:
                    # Replace string tool names with corrected versions if available,
                    # leave complex tool objects (e.g. MCP dictionaries) as-is
                    if isinstance(agent_tool, str):
                        new_agent_tools.append(corrections.get(agent_tool, agent_tool))
                    else:
                        new_agent_tools.append(agent_tool)

                tool["tools"] = new_agent_tools

            # CodedTools deriving from BranchActivation declare the agents they might call
            # in args.tools rather than in tools (see "tools (args)" in agent_hocon_reference.md).
            # ToolsShapeValidator.validate_args_tools and ConnectivityReporter (through
            # AbstractNetworkValidator.coerce_args_tools) both read that key, so a reference
            # left under the old name would make connectivity report an edge to an agent that
            # no longer exists, and the coded tool itself would fail to find its renamed child.
            self.correct_args_tools(tool, corrections)

        # Spit out information about errors
        logger = logging.getLogger(self.__class__.__name__)
        for error in errors:
            logger.error(error)

        # Spit out information about corrections
        for original, correction in corrections.items():
            logger.info("Correcting %s to %s", str(original), str(correction))

        return basis_config

    @staticmethod
    def correct_args_tools(tool: Dict[str, Any], corrections: Dict[str, str]) -> None:
        """
        Rewrites, in place, the agent-name references a tool holds in its args.tools
        using the given corrections table.

        args.tools is accepted in the same two shapes ToolsShapeValidator.validate_args_tools
        and AbstractNetworkValidator.coerce_args_tools understand: a list of agent-name
        strings, or a dict of label -> agent-name string. Only string entries (list elements,
        dict values) are rewritten. Dict keys, non-string entries and any other shape are left
        untouched, since ToolsShapeValidator is the place that reports malformed shapes.
        Neither "args" nor "args.tools" is created where absent.

        :param tool: The agent/tool spec dictionary whose args.tools is corrected in place
        :param corrections: A dictionary of original agent name -> corrected agent name
        """
        args: Any = tool.get("args")
        if not isinstance(args, dict) or "tools" not in args:
            # Nothing to correct.  Do not create args or args.tools here: this filter only
            # rewrites names and must otherwise hand every tool back value-equal to its input,
            # so it never invents keys the author did not write.
            return

        args_tools: Any = args.get("tools")
        if isinstance(args_tools, list):
            # List form: every element is an agent name. Rewrite by index so that the list
            # object and any non-string entries stay exactly as they were given.
            args_tools_list: List[str] = args_tools
            index: int = 0
            agent_tool: Any = None
            for index, agent_tool in enumerate(args_tools_list):
                if isinstance(agent_tool, str):
                    agent_tool_string: str = agent_tool
                    args_tools_list[index] = corrections.get(agent_tool_string, agent_tool_string)
        elif isinstance(args_tools, dict):
            # Dict form: label -> agent name.  Only the values are names; the labels are the
            # coded tool's own lookup keys and must stay stable.  Assigning to existing keys
            # while iterating is safe; only adding or removing keys would not be.
            args_tools_dict: Dict[str, Any] = args_tools
            label: str = None
            agent_tool: Any = None
            for label, agent_tool in args_tools_dict.items():
                if isinstance(agent_tool, str):
                    agent_tool_string: str = agent_tool
                    args_tools_dict[label] = corrections.get(agent_tool_string, agent_tool_string)
        # Any other shape is malformed. ToolsShapeValidator reports it, so leave it alone.

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
