
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

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.interfaces.dictionary_validator import DictionaryValidator


class AbstractNetworkValidator(DictionaryValidator):
    """
    An abstract interface for validating agent network content with a little bit of
    common policy thrown in.
    """

    def validate(self, candidate: Dict[str, Any]) -> List[str]:
        """
        Validate the agent network

        :param candidate: The agent network or name -> spec dictionary to validate
        :return: A list of error messages
        """
        errors: List[str] = []

        if not candidate:
            errors.append("Agent network is empty.")
            return errors

        # We can validate either from a top-level agent network,
        # or from the list of tools from the agent spec.
        name_to_spec: Dict[str, Any] = self.get_name_to_spec(candidate)

        name_to_spec_errors: List[str] = self.validate_name_to_spec_dict(name_to_spec)
        errors.extend(name_to_spec_errors)

        return errors

    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        Validate the agent network, specifically in the form of a name -> agent spec dictionary.

        :param name_to_spec: The name -> agent spec dictionary to validate
        :return: A list of error messages
        """
        raise NotImplementedError

    @staticmethod
    def get_name_to_spec(agent_network: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param agent_network: The top-level agent network or tools dictionary
        :return: The agent name -> single agent spec dictionary of the agent network
        """
        if agent_network is None:
            return None

        if "tools" not in agent_network:
            # Assume we already have the name -> spec dictionary
            return agent_network

        name_to_spec: Dict[str, Any] = {}
        agents: List[Dict[str, Any]] = agent_network.get("tools", [])
        for one_agent in agents:
            name_to_spec[one_agent.get("name")] = one_agent

        return name_to_spec

    @staticmethod
    def is_url_or_path(tool: str) -> bool:
        """
        Check if a tool string is a URL or file path (not an agent name).

        :param tool: The tool string to check
        :return: True if tool is a URL or path, False otherwise
        """
        return (tool.startswith("/") or
                tool.startswith("http://") or
                tool.startswith("https://"))

    @staticmethod
    def remove_dictionary_tools(down_chains: List[Any]) -> List[str]:
        """
        Sometimes tool lists have dictionary entries to support servers-based tools
        that need more than just a string.  For instance MCP servers.
        :param  down_chains: List of tools
        :return: List of tools without dictionary entries
        """
        safe_list: List[str] = []
        for tool in down_chains:
            if isinstance(tool, str):
                safe_list.append(tool)
        return safe_list

    @staticmethod
    def coerce_tools(agent_spec: Dict[str, Any]) -> List[Any]:
        """
        Return the agent's `tools` as a list, coercing malformed values to empty.

        Callers that traverse the connectivity graph (front-man detection,
        reachability, missing nodes, cycles) should use this rather than reading
        `tools` directly so they do not crash on `str + list` or iterate the
        characters of a string. The shape contract this enforces matches
        ToolsShapeValidator.validate_tools, which is the place that reports the
        shape error to the user.

        :param agent_spec: The agent specification dictionary
        :return: The agent's `tools` list, or an empty list if the value is malformed.
        """
        no_tools: List[Any] = []
        extractor = DictionaryExtractor(agent_spec)
        tools: Any = extractor.get("tools", no_tools)
        if isinstance(tools, list):
            return tools
        return no_tools

    @staticmethod
    def coerce_args_tools(agent_spec: Dict[str, Any]) -> List[Any]:
        """
        Return `args.tools` as a list of values, coercing malformed shapes to empty.

        `args.tools` is the convention coded tools use to declare downstream agents.
        It may be a dict of label -> agent name (the values are the agent names)
        or a list of agent names; anything else is coerced to empty. The shape
        contract this enforces matches ToolsShapeValidator.validate_args_tools,
        which is the place that reports the shape error to the user.

        :param agent_spec: The agent specification dictionary
        :return: The combined list of agent names referenced by `args.tools`, or
                empty if the value is missing or malformed.
        """
        no_tools: List[Any] = []
        extractor = DictionaryExtractor(agent_spec)
        args_tools: Any = extractor.get("args.tools", no_tools)
        if isinstance(args_tools, dict):
            return list(args_tools.values())
        if isinstance(args_tools, list):
            return args_tools
        return no_tools
