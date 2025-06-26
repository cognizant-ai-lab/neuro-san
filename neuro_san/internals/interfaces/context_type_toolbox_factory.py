
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from typing import Any
from typing import Dict
from typing import List
from typing import Union

from langchain_core.tools import BaseTool


class ContextTypeToolboxFactory:
    """
    Interface for factory classes that create tools or toolkits from a toolbox.

    Most methods accept a configuration dictionary, where each key is a tool name, and each value is
    a dictionary containing the corresponding tool's setup information. The configuration dictionary
    supports the following keys for each tool.

    Langchain's Tool:
        - "class":  The class of the tool or toolkit.
                    This key is required. A ValueError will be raised if not provided.

        - "args":   A dictionary of constructor or class method arguments used to instantiate the tool
                    or toolkit.

    Coded Tool:
        - "class":  Module and class in the format of tool_module.ClassName.

        - "description":  When and how to use the tool.

        - "parameters":  Information on arguments of the tool.
    """

    def load(self):
        """
        Goes through the process of loading any user extensions and/or configuration
        files
        """
        raise NotImplementedError

    def create_tool_from_toolbox(
            self,
            tool_name: str,
            user_args: Dict[str, Any]
    ) -> Union[BaseTool, Dict[str, Any], List[BaseTool]]:
        """
        Create a tool instance from the fully-specified tool config.
        :param tool_name: The name of the tool to instantiate.
        :param user_args: Arguments provided by the user, which override the args in config file.
        :return: A tool instance native to the context type.
                Can raise a ValueError if the config's class or tool_name value is
                unknown to this method.
        """
        raise NotImplementedError

    def get_shared_coded_tool_class(self, tool_name: str) -> str:
        """
        Get class of the shared coded tool from toolbox

        :param tool_name: The name of the tool
        :return: The class of the coded tool from toolbox
        """
        raise NotImplementedError

    def get_tool_info(self, tool_name: str) -> Dict[str, Any]:
        """
        :param tool_name: The name of the tool.
        :return: The toolbox dictionary entry for the tool name
        """
        raise NotImplementedError
