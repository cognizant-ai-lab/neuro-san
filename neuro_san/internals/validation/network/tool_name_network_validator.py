
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

import re

from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class ToolNameNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator that looks for correct tool names in an agent network
    """

    # This comes from the langchain error message that happens when a tool name is not valid
    TOOL_NAME_PATTERN: str = r"^[a-zA-Z0-9_-]+$"

    def __init__(self):
        """
        Constructor
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        Validate the agent network, specifically in the form of a name -> agent spec dictionary.

        :param name_to_spec: The name -> agent spec dictionary to validate
        :return: List of errors indicating agents than have invalid names
        """
        errors: List[str] = []

        # Be sure all agent names are valid per the regex above.
        agent_name: str = None
        agent: Dict[str, Any] = None
        for agent_name, agent in name_to_spec.items():
            spec_name: str = agent.get("name")
            if not re.match(self.TOOL_NAME_PATTERN, agent_name) or \
                    not re.match(self.TOOL_NAME_PATTERN, spec_name):
                error_msg = f"{agent_name} must match the regex '{self.TOOL_NAME_PATTERN}'"
                errors.append(error_msg)

        # Only warn if there is a problem
        if len(errors) > 0:
            self.logger.warning(str(errors))

        return errors
