
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
from typing import Iterable
from typing import List
from typing import Set

from logging import getLogger
from logging import Logger

from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class KeywordNetworkValidator(AbstractNetworkValidator):
    """
    AgentNetworkValidator that looks for correct keywords in an agent network
    """

    ALL_KEYWORDS: Set[str] = {"description", "instructions", "tools"}

    def __init__(self, keywords: Iterable[str] = None, network_name: str = None):
        """
        Constructor

        :param keywords: Iterable of keyword names to validate.
                         If None, all keywords are validated.
        :param network_name: The agent network name for diagnostic log lines
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.keywords: Set[str] = set(keywords) if keywords is not None else self.ALL_KEYWORDS
        self.network_name: str = network_name

    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        Validate the agent network, specifically in the form of a name -> agent spec dictionary.

        :param name_to_spec: The name -> agent spec dictionary to validate
        :return: List of errors indicating agents and missing keywords
        """
        errors: List[str] = []

        self.logger.debug("Validating %s agent network keywords...", self.network_name)

        for agent_name, agent in name_to_spec.items():
            if "description" in self.keywords:
                errors.extend(self.validate_description(agent_name, agent))
            if "instructions" in self.keywords:
                errors.extend(self.validate_instructions(agent_name, agent))
            if "tools" in self.keywords:
                errors.extend(self.validate_tools(agent_name, agent))

        # Only warn if there is a problem
        if len(errors) > 0:
            self.logger.warning(str(errors))

        return errors

    @staticmethod
    def validate_description(agent_name: str, agent: Dict[str, Any]) -> List[str]:
        """
        Validate that 'function.description' is a non-empty string when present.

        :param agent_name: The name of the agent being validated
        :param agent: The agent spec dictionary
        :return: A list of error messages
        """
        errors: List[str] = []
        function: Any = agent.get("function")
        if function is None:
            return errors
        if not isinstance(function, dict):
            errors.append(
                f"{agent_name} 'function' must be a dict,"
                f" got {type(function).__name__}."
            )
            return errors
        description: Any = function.get("description")
        if description is not None:
            if not isinstance(description, str):
                errors.append(
                    f"{agent_name} 'function.description' must be a str,"
                    f" got {type(description).__name__}."
                )
            elif description.strip() == "":
                errors.append(f"{agent_name} 'function.description' cannot be empty.")
        return errors

    @staticmethod
    def validate_instructions(agent_name: str, agent: Dict[str, Any]) -> List[str]:
        """
        Validate that 'instructions' is a non-empty string when present.

        :param agent_name: The name of the agent being validated
        :param agent: The agent spec dictionary
        :return: A list of error messages
        """
        errors: List[str] = []
        instructions: Any = agent.get("instructions")
        if instructions is not None:
            if not isinstance(instructions, str):
                errors.append(
                    f"{agent_name} 'instructions' must be a str,"
                    f" got {type(instructions).__name__}."
                )
            elif instructions.strip() == "":
                errors.append(f"{agent_name} 'instructions' cannot be empty.")
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
