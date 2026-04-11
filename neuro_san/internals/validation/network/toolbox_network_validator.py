
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

from logging import getLogger
from logging import Logger

from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class ToolboxNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator for toolbox references.
    """

    def __init__(self, tools: Dict[str, Any]):
        """
        Constructor

        :param tools: A dictionary of tools, as read in from a toolbox_info.hocon file
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.tools: Dict[str, Any] = tools

    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        Validate the agent network, specifically in the form of a name -> agent spec dictionary.

        :param name_to_spec: The name -> agent spec dictionary to validate
        :return: A list of error messages
        """
        errors: List[str] = []

        self.logger.info("Validating toolbox agents...")

        for agent_name, agent in name_to_spec.items():
            if agent.get("instructions") is None:  # This is a toolbox agent
                if self.tools is None or not isinstance(self.tools, Dict):
                    errors.append(f"Toolbox is unavailable. Cannot create Toolbox agent '{agent_name}'.")
                elif agent_name not in self.tools:
                    errors.append(f"Toolbox agent '{agent_name}' has no matching tool in toolbox.")
                elif agent.get("tools"):
                    errors.append(
                        "Toolbox agent cannot have 'tools'. "
                        f"[{agent.get('tools')}] cannot be under Toolbox agent '{agent_name}'"
                    )

        return errors
