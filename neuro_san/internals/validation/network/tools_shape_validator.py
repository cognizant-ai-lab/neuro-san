
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

from logging import Logger
from logging import getLogger

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class ToolsShapeValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator that checks the shape of fields that downstream
    structural validators traverse:
      - `tools` must be a list whose elements are each a str or dict.
      - `args.tools`, when present, must be either a dict (label -> agent name,
        the coded-tool convention) or a list of names.

    Other validators (UnreachableNodesNetworkValidator, MissingNodesNetworkValidator,
    etc.) iterate or concatenate these fields and would crash or produce nonsense
    results on a malformed value. This validator surfaces those shape errors
    upstream so the structural phase can be gated on shape soundness.

    The static methods `coerce_tools` and `coerce_args_tools` expose the same
    shape contract in a tolerant form: they return a safe list (empty when
    the value is malformed) and optionally log a warning. Callers that
    cannot assume this validator ran (e.g., StructureNetworkValidator users)
    can use these helpers to traverse defensively.
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

        for agent_name, agent in name_to_spec.items():
            errors.extend(self.validate_tools(agent_name, agent))
            errors.extend(self.validate_args_tools(agent_name, agent))

        if len(errors) > 0:
            # Only warn if there is a problem
            self.logger.warning(str(errors))

        return errors

    @staticmethod
    def validate_tools(agent_name: str, agent: Dict[str, Any]) -> List[str]:
        """
        Validate that 'tools' is a list where each element is a str or dict.

        :param agent_name: The name of the agent being validated
        :param agent: The agent spec dictionary
        :return: A list of error messages
        """
        errors: List[str] = []
        tools: Any = agent.get("tools")
        if tools is not None and not isinstance(tools, list):
            errors.append(
                f"{agent_name} 'tools' must be a list, got {type(tools).__name__}."
            )
        elif isinstance(tools, list):
            for i, tool in enumerate(tools):
                if not isinstance(tool, (str, dict)):
                    errors.append(
                        f"{agent_name} 'tools[{i}]' must be a str or dict,"
                        f" got {type(tool).__name__}."
                    )
        return errors

    @staticmethod
    def validate_args_tools(agent_name: str, agent: Dict[str, Any]) -> List[str]:
        """
        Validate that 'args.tools', if present, is either a dict or a list.

        :param agent_name: The name of the agent being validated
        :param agent: The agent spec dictionary
        :return: A list of error messages
        """
        errors: List[str] = []
        args: Any = agent.get("args")
        if not isinstance(args, dict):
            return errors
        if "tools" not in args:
            return errors
        args_tools: Any = args.get("tools")
        if not isinstance(args_tools, (dict, list)):
            errors.append(
                f"{agent_name} 'args.tools' must be a dict or list,"
                f" got {type(args_tools).__name__}."
            )
        return errors

    @staticmethod
    def coerce_tools(agent_spec: Dict[str, Any], agent_name: str,
                     logger: Logger = None) -> List[Any]:
        """
        Return the agent's `tools` as a list, coercing malformed values to empty.

        Callers that traverse the connectivity graph (front-man detection,
        reachability) should use this rather than reading `tools` directly so
        they do not crash on `str + list` or iterate the characters of a string.

        :param agent_spec: The agent specification dictionary
        :param agent_name: The name of the agent, used in the warning message
        :param logger: Optional logger; when provided, a warning is emitted on coercion
        :return: The agent's `tools` list, or an empty list if the value is malformed.
        """
        no_tools: List[Any] = []
        extractor = DictionaryExtractor(agent_spec)
        tools: Any = extractor.get("tools", no_tools)
        if isinstance(tools, list):
            return tools
        if logger is not None:
            logger.warning(
                "Agent '%s' has 'tools' that is not a list. Treating as empty for traversal.",
                agent_name,
            )
        return no_tools

    @staticmethod
    def coerce_args_tools(agent_spec: Dict[str, Any], agent_name: str,
                          logger: Logger = None) -> List[Any]:
        """
        Return `args.tools` as a list of values, coercing malformed shapes to empty.

        `args.tools` is the convention coded tools use to declare downstream agents.
        It may be a dict of label -> agent name (the values are the agent names)
        or a list of agent names. Anything else is coerced to empty.

        :param agent_spec: The agent specification dictionary
        :param agent_name: The name of the agent, used in the warning message
        :param logger: Optional logger; when provided, a warning is emitted on coercion
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
        if logger is not None:
            logger.warning(
                "Agent '%s' has 'args.tools' that is neither a dict nor a list. "
                "Treating as empty for traversal.",
                agent_name,
            )
        return no_tools
