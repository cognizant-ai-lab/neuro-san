
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


class DefaultParametersConfigFilter(ConfigFilter):
    """
    ConfigFilter implementation that gives an LLM sub-agent a single required
    "inquiry" string parameter when its function block has no "parameters", or a null one.
    A calling LLM sees a sub-agent without parameters as a tool that takes no arguments,
    so the input prompt that BranchActivation builds from the call's arguments is empty
    and the sub-agent never gets the request. With the default parameters, BranchActivation
    passes on only "inquiry", so a coded tool that calls such an agent sends "inquiry".

    The front man is left alone, because it does not build its input from its parameters.
    A user reaches it through the chat, and an MCP client through a chat request.
    Another network reaches it through an external agent tool, which
    ExternalAgentToolCreator gives a required "inquiry" parameter when the front man
    declares none, and the arguments arrive as the front man's chat message.

    Coded tools and toolbox agents, which do not run as LLM agents, and agents without
    a function block, which cannot be called, are left alone too. An agent that gives
    "parameters" outside its function block is left alone with a warning.
    """

    # The parameters of an LLM sub-agent whose function block has no "parameters", or a null one.
    DEFAULT_PARAMETERS: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "inquiry": {
                "type": "string",
                "description": "The request to send to this agent.",
            },
        },
        "required": ["inquiry"],
    }

    def __init__(self) -> None:
        """
        Constructor
        """
        super().__init__()
        self.logger: Logger = getLogger(self.__class__.__name__)

    @override
    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adds the default parameters to each LLM sub-agent whose function block has no "parameters", or a null one.

        :param basis_config: The agent network config dictionary. It is never modified.
        :return: basis_config itself when no agent needs the default parameters,
                otherwise a copy of it with the parameters added
        """
        if basis_config is None:
            return basis_config

        tools: Any = basis_config.get("tools")
        if not isinstance(tools, list) or len(tools) == 0:
            # Nothing to do. Exit early.
            return basis_config

        result_config: Dict[str, Any] = basis_config

        # Add the default parameters to each LLM sub-agent whose function block has no "parameters", or a null one.
        index: int = 0
        tool: Any = None
        for index, tool in enumerate(tools):
            if index == 0:
                # The front man is the first tool in the list, as in AgentNetwork.find_front_man().
                # Users, MCP clients and external callers all send it a chat message, so it needs no default.
                continue
            if not self.needs_default_parameters(tool):
                continue

            tool_dict: Dict[str, Any] = tool
            if "parameters" in tool_dict:
                # The validators check top-level parameters, even null ones, only when the
                # function block has none, so the function block stays as it is.
                self.logger.warning("The top-level parameters of agent %s are not used: parameters only work "
                                    "inside the function block, so put them in function.parameters.",
                                    tool_dict.get("name"))
                continue

            if result_config is basis_config:
                # Copy only when something changes, so a network without such agents
                # comes back as the very same dictionary.
                result_config = deepcopy(basis_config)

            result_tools: List[Any] = result_config.get("tools")
            # A new function block, so other agents that share this one keep it as it is.
            new_function: Dict[str, Any] = dict(result_tools[index].get("function"))
            new_function["parameters"] = deepcopy(DefaultParametersConfigFilter.DEFAULT_PARAMETERS)
            result_tools[index]["function"] = new_function

        return result_config

    @staticmethod
    def needs_default_parameters(tool: Any) -> bool:
        """
        Tells whether an agent is an LLM agent whose function block has no "parameters", or a null one.

        :param tool: An entry of the "tools" list, other than the front man
        :return: True when the agent needs the default parameters
        """
        if not isinstance(tool, dict):
            # Not an agent spec.
            return False

        tool_dict: Dict[str, Any] = tool
        if tool_dict.get("class") is not None or tool_dict.get("toolbox") is not None:
            # Not an LLM agent: BranchActivationPrepper takes only agents without a class,
            # after ToolboxActivationPrepper has taken the toolbox agents.
            return False

        function: Any = tool_dict.get("function")
        if not isinstance(function, dict):
            # Without a function block the agent cannot be called, and a malformed one
            # is reported by the validators.
            return False

        function_dict: Dict[str, Any] = function
        return function_dict.get("parameters") is None
