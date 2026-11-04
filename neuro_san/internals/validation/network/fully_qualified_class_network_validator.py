
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

from importlib.machinery import ModuleSpec
from importlib.util import find_spec
from logging import getLogger
from logging import Logger

from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class FullyQualifiedClassNetworkValidator(AbstractNetworkValidator):
    """
    AgentNetworkValidator that requires every CodedTool "class" reference in an agent network
    to be fully-qualified, that is, resolvable from the PYTHONPATH without the agent network
    name or AGENT_TOOL_PATH. This suits agent networks whose name does not map to a package
    under AGENT_TOOL_PATH, such as those fetched by URL.

    A reference is fully-qualified when it has the form "<module>.<ClassName>" and the
    top-level package of its module is findable on the PYTHONPATH. Only the top-level
    package is located, so validation never imports a module or runs its code.
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
        :return: List of errors indicating agents with class references that are not fully-qualified
        """
        errors: List[str] = []

        self.logger.debug("Validating %s agent network class references...", self.network_name)

        # Check the class reference of each agent that has one
        agent_name: str = None
        agent: Dict[str, Any] = None
        for agent_name, agent in name_to_spec.items():
            if not isinstance(agent, dict):
                # ToolsShapeValidator reports malformed agent specs.
                continue
            class_ref: Any = agent.get("class")
            if class_ref is None:
                continue
            errors.extend(self.validate_class_ref(agent_name, class_ref))

        # Only warn if there is a problem
        if len(errors) > 0:
            self.logger.warning(str(errors))

        return errors

    @staticmethod
    def validate_class_ref(agent_name: str, class_ref: Any) -> List[str]:
        """
        Validate that a single class reference is fully-qualified.

        :param agent_name: The name of the agent being validated
        :param class_ref: The value of the agent's "class" key
        :return: A list of error messages
        """
        errors: List[str] = []

        if not isinstance(class_ref, str):
            errors.append(f"{agent_name} 'class' must be a str, got {type(class_ref).__name__}.")
            return errors

        # A relative import name needs a package to resolve against, so it cannot be fully-qualified.
        module_name: str = class_ref.rpartition(".")[0]
        if len(module_name) == 0 or class_ref.startswith("."):
            errors.append(f"{agent_name} 'class' value '{class_ref}' must be a fully-qualified "
                          "'<package>.<module>.<ClassName>' reference.")
            return errors

        top_level_package: str = module_name.split(".")[0]
        if not FullyQualifiedClassNetworkValidator.is_top_level_findable(top_level_package):
            errors.append(f"{agent_name} 'class' value '{class_ref}' must be fully-qualified, but its "
                          f"top-level package '{top_level_package}' is not on the PYTHONPATH.")

        return errors

    @staticmethod
    def is_top_level_findable(top_level_package: str) -> bool:
        """
        Determine whether a top-level package is on the PYTHONPATH, without importing it.

        :param top_level_package: A module name without any dots
        :return: True if the package can be found, False otherwise
        """
        try:
            spec: ModuleSpec = find_spec(top_level_package)
        except ValueError:
            # The module is already in sys.modules, but has no __spec__.
            return True
        return spec is not None
