
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
    results on a malformed value. This validator surfaces those shape errors so
    callers see a readable message instead of a downstream TypeError/AttributeError.

    The matching defensive readers `AbstractNetworkValidator.coerce_tools` and
    `coerce_args_tools` enforce the same shape contract in a tolerant form
    (returning an empty list when the value is malformed) for use by validators
    that traverse the connectivity graph.
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

    def validate_tools(self, agent_name: str, agent: Dict[str, Any]) -> List[str]:
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

    def validate_args_tools(self, agent_name: str, agent: Dict[str, Any]) -> List[str]:
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
