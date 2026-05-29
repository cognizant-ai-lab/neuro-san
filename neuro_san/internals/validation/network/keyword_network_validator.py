
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

    ALL_KEYWORDS: Set[str] = {"description", "instructions"}

    def __init__(self, keywords: Iterable[str] = None):
        """
        Constructor

        :param keywords: Iterable of keyword names to validate.
                         If None, all keywords are validated.

        Note: `tools` shape validation lives in ToolsShapeValidator (a structure
        concern, not a keyword concern), and is not handled by this class.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.keywords: Set[str] = set(keywords) if keywords is not None else self.ALL_KEYWORDS

    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        Validate the agent network, specifically in the form of a name -> agent spec dictionary.

        :param name_to_spec: The name -> agent spec dictionary to validate
        :return: List of errors indicating agents and missing keywords
        """
        errors: List[str] = []

        self.logger.info("Validating agent network keywords...")

        for agent_name, agent in name_to_spec.items():
            if "description" in self.keywords:
                errors.extend(self.validate_description(agent_name, agent))
            if "instructions" in self.keywords:
                errors.extend(self.validate_instructions(agent_name, agent))

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
