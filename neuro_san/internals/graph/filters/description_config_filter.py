
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

from copy import deepcopy
from logging import getLogger
from logging import Logger

from typing_extensions import override

from leaf_common.config.config_filter import ConfigFilter


class DescriptionConfigFilter(ConfigFilter):
    """
    ConfigFilter implementation that lets an agent give its description as a
    top-level "description" instead of inside its "function" block.

    The description goes into the agent's function block, which is made when the
    agent has none. No parameters are added. When an LLM sub-agent declares none,
    InternalAgentToolCreator adds a default "inquiry" parameter to the tool
    through which it is called.

    A function block with its own description is left as it is, and so is a
    "function" value that is not a dictionary, which the validators report. Any
    other top-level description that cannot be used, such as one on a toolbox
    agent, is reported with a warning.
    """

    def __init__(self) -> None:
        """
        Constructor
        """
        super().__init__()
        self.logger: Logger = getLogger(self.__class__.__name__)

    @override
    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Puts each agent's top-level description into its function block.

        :param basis_config: The agent network config dictionary. It is never modified.
        :return: basis_config itself when no agent gives a description to use,
                otherwise a copy of it with the function blocks filled in
        """
        if basis_config is None:
            return basis_config

        tools: Any = basis_config.get("tools")
        if not isinstance(tools, list) or len(tools) == 0:
            # Nothing to do. Exit early.
            return basis_config

        result_config: Dict[str, Any] = basis_config

        # Fill in the function block of each agent that gives a usable top-level description.
        index: int = 0
        tool: Any = None
        for index, tool in enumerate(tools):
            if not isinstance(tool, dict):
                # Not an agent spec, so there is nothing to fill in.
                continue

            tool_dict: Dict[str, Any] = tool
            if tool_dict.get("description") is None or not self.lacks_description(tool_dict.get("function")):
                # There is no top-level description, or the function block has its own or is malformed.
                continue

            reason: str = self.find_reason_not_used(tool_dict)
            if reason is not None:
                self.logger.warning("The top-level description of agent %s is not used: %s.",
                                    tool_dict.get("name"), reason)
                continue

            if result_config is basis_config:
                # Copy only when something changes, so a network without such agents
                # comes back as the very same dictionary.
                result_config = deepcopy(basis_config)

            result_tools: List[Any] = result_config.get("tools")
            result_tools[index]["function"] = self.make_function(result_tools[index])

        return result_config

    @staticmethod
    def lacks_description(function: Any) -> bool:
        """
        Tells whether a function block is missing or has no description of its own.

        :param function: The value of the agent's "function" key
        :return: True when the value is None or a dictionary without a description.
                False otherwise, including for a malformed value that the validators report.
        """
        if function is None:
            return True
        if not isinstance(function, dict):
            return False
        function_dict: Dict[str, Any] = function
        return function_dict.get("description") is None

    @staticmethod
    def find_reason_not_used(tool: Dict[str, Any]) -> str:
        """
        Finds why the top-level description of an agent cannot go into its function block.

        :param tool: An agent spec with a top-level description and no function description
        :return: The reason, worded for a log message, or None when the description can be used
        """
        reason: str = None
        description: Any = tool.get("description")
        if tool.get("toolbox") is not None:
            reason = "a toolbox agent gets its function from the toolbox"
        elif tool.get("parameters") is not None:
            reason = "parameters only work inside the function block, so put them in function.parameters"
        elif not isinstance(description, str):
            reason = f"it must be a string, not {type(description).__name__}"
        elif len(description.strip()) == 0:
            reason = "it is blank"
        return reason

    @staticmethod
    def make_function(tool: Dict[str, Any]) -> Dict[str, Any]:
        """
        Makes the function block of an agent from its top-level description.

        :param tool: An agent spec with a usable top-level description and no function description
        :return: A new function block: the agent's own function block, if any, with the description added
        """
        function: Dict[str, Any] = {}
        own_function: Dict[str, Any] = tool.get("function")
        if own_function is not None:
            # Keep what the function block already has, such as a sly_data_schema
            # that DefaultsConfigFilter put into the front man's function block.
            function = dict(own_function)
        function["description"] = tool.get("description")
        return function
