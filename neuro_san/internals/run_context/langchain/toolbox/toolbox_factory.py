
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
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Type
from typing import Union

import os

from langchain.tools import BaseTool
from langchain_community.agent_toolkits.base import BaseToolkit
from pydantic import BaseModel

from leaf_common.config.dictionary_overlay import DictionaryOverlay
from leaf_common.config.resolver import Resolver

from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.run_context.langchain.toolbox.toolbox_info_restorer import ToolboxInfoRestorer
from neuro_san.internals.run_context.langchain.util.argument_validator import ArgumentValidator


class ToolboxFactory(ContextTypeToolboxFactory):
    """
    A factory class for creating instances of various tools defined in the toolbox.

    This class provides an interface to instantiate different tools based on the specified langchain base tools
    and predefined coded tools.

    This approach standardizes tool creation and simplifies integration with agents requiring predefined tools.

    ### Extending the Class

        To integrate additional tools, add a tool configuration file in JSON or HOCON format
        and set its path to the environment variable "AGENT_TOOLBOX_INFO_FILE".

        The configuration should follow this structure

        for langchain's tools:
        - The tool name serves as a key.
        - The corresponding value should be a dictionary with:
        - "class": The fully qualified class name of the tool.
        - "args": A dictionary of arguments required for the tool's initialization,
            which may include nested class configurations.

        for coded tools:
        - The tool name serves as a key.
        - The corresponding value should be a dictionary with:
        - "class": Module and class in the format of tool_module.ClassName where tool_module is in
                    AGENT_TOOL_PATH or neuro_san/coded_tools.
        - "description": When and how to use the tool.
        - "parameters": Information on arguments of the tool.
            See "parameters" in https://github.com/cognizant-ai-lab/neuro-san/blob/main/docs/agent_hocon_reference.md

        The default toolbox config file can be seen at
        "neuro_san/internals/run_context/langchain/toolbox/toolbox_info.hocon"
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Constructor

        :param config: The config dictionary which may or may not contain
                       keys for the context_type and toolbox_info_file
        """
        self.toolbox_infos: Dict[str, Any] = {}
        self.overlayer = DictionaryOverlay()

        # Get user toolbox info file path with the following priority:
        # 1. "agent_toolbox_info_file" from agent network hocon
        # 2. "toolbox_info_file" from agent network hocon
        # 3. "AGENT_TOOLBOX_INFO_FILE" from environment variable
        if config:
            raw_toolbox_info_file: str = (
                config.get("agent_toolbox_info_file")
                or config.get("toolbox_info_file")
                or os.getenv("AGENT_TOOLBOX_INFO_FILE")
            )
        else:
            raw_toolbox_info_file = os.getenv("AGENT_TOOLBOX_INFO_FILE")

        if raw_toolbox_info_file is not None and not isinstance(raw_toolbox_info_file, str):
            raise TypeError(
                "The values of 'agent_toolbox_info_file', 'toolbox_info_file', and "
                "the 'AGENT_TOOLBOX_INFO_FILE' environment variable must be strings. "
                f"Got {type(raw_toolbox_info_file).__name__} instead."
            )

        self.toolbox_info_file: str = raw_toolbox_info_file

    def load(self):
        """
        Loads the base tool information from hocon files.
        """
        restorer = ToolboxInfoRestorer()
        self.toolbox_infos = restorer.restore()

        # Mix in user-specified toolbox info, if available.
        if self.toolbox_info_file:
            extra_toolbox_infos: Dict[str, Any] = restorer.restore(file_reference=self.toolbox_info_file)
            self.toolbox_infos = self.overlayer.overlay(self.toolbox_infos, extra_toolbox_infos)

    def create_tool_from_toolbox(
            self,
            tool_name: str,
            user_args: Dict[str, Any] = None
    ) -> Union[BaseTool, Dict[str, Any], List[BaseTool]]:
        """
        Resolves dependencies and instantiates the requested tool.

        :param tool_name: The name of the tool to instantiate.
        :param user_args: Arguments provided by the user, which override the config file.
        :return: - Instantiated tool if "class" of tool_name points to a BaseTool class
                 - A list of tools if "class of "tool_name points to a BaseToolkit class.
                 - A dict of tool's "description" and "parameters" if tool_name points to a CodedTool
        """
        empty: Dict[str, Any] = {}

        tool_info: Dict[str, Any] = self.toolbox_infos.get(tool_name)
        if not tool_info:
            raise ValueError(f"Tool '{tool_name}' is not defined in {self.toolbox_info_file}.")

        if not isinstance(tool_info, Dict):
            raise ValueError(f"The value for the {tool_name} key must be a dictionary.")

        if "class" not in tool_info:
            raise ValueError(
                "Missing required key: 'class'.\n"
                "Each tool must include a 'class' key:\n"
                "- For Langchain base tools: use the full class path "
                "(e.g., 'langchain_community.tools.bing_search.BingSearchResults')\n"
                "- For shared CodedTools: use 'module.Class' format (e.g., 'websearch.WebSearch')"
            )

        # If "description" in the tool info, then it is a shared coded tool.
        # Return dictionary of tool's description and parameters.
        if "description" in tool_info:
            return tool_info

        # Instantiate the main tool or toolkit class
        tool_class: Type[Any] = self._resolve_class(tool_info.get("class"))
        # Recursively resolve arguments (including wrapper dependencies)
        resolved_args: Dict[str, Any] = self._resolve_args(tool_info.get("args", empty))
        # Merge with user arguments where user_args get the priority
        final_args: Dict[str, Any] = self.overlayer.overlay(resolved_args, user_args) if user_args else resolved_args

        # Use the "from_{tool_name}_api_wrapper" method if available, otherwise the constructor
        callable_obj: Union[Type[BaseTool], Type[BaseToolkit], Callable[..., Any]] = \
            self._get_from_api_wrapper_method(tool_class) or tool_class

        # Validate and instantiate
        ArgumentValidator.check_invalid_args(callable_obj, final_args)
        # Instance can be a BaseTool or a BaseToolkit
        instance: Union[BaseTool, BaseToolkit] = callable_obj(**final_args)

        # If the instantiated class has "get_tools()", assume it's a toolkit and return a list of tools
        if hasattr(instance, "get_tools") and callable(instance.get_tools):
            return instance.get_tools()

        return instance

    def _resolve_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursive resolves arguments when there is a wrapper class as an argument,
        otherwise return args as a dictionary.

        :param args: The arguments to resolve.
        :return: A dictionary of resolved arguments.
        """
        empty: Dict[str, Any] = {}

        resolved_args: Dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, dict) and "class" in value:
                # If the argument is a class definition, resolve and instantiate it
                nested_class: BaseModel = self._resolve_class(value.get("class"))
                nested_args: Dict[str, Any] = self._resolve_args(value.get("args", empty))
                ArgumentValidator.check_invalid_args(nested_class, nested_args)
                resolved_args[key] = nested_class(**nested_args)
            else:
                # Otherwise, keep primitive values as they are
                resolved_args[key] = value
        return resolved_args

    def _resolve_class(self, class_path: str) -> Type[BaseTool]:
        """
        Uses Resolver to dynamically import a class.

        :param class_path: Full class path (e.g., "package.module.ClassName").
        :return: The resolved class type.
        """
        class_split: List[str] = class_path.split(".")
        if len(class_split) <= 2:
            raise ValueError(
                f"Value in 'class' in {self.toolbox_info_file} must be of the form "
                "'<package_name>.<module_name>.<ClassName>'"
            )

        # Extract module and class details
        packages: List[str] = [".".join(class_split[:-2])]
        class_name: str = class_split[-1]
        resolver = Resolver(packages)

        # Resolve class
        try:
            return resolver.resolve_class_in_module(class_name, module_name=class_split[-2])
        except AttributeError as exception:
            raise ValueError(f"Class {class_path} not found in PYTHONPATH") from exception

    def _get_from_api_wrapper_method(
        self,
        tool_class: Union[Type[BaseTool], Type[BaseToolkit]]
    ) -> Optional[Callable[..., Any]]:
        """
        Get a 'from_{tool_name}_api_wrapper' class method from the tool class if available.

        :param tool_class: BaseTool or BaseToolkit class to check for the method.
        :return: The method if found, None otherwise.
        """
        for attr_name in dir(tool_class):
            if attr_name.startswith("from") and attr_name.endswith("api_wrapper"):
                attr: Callable[..., Any] = getattr(tool_class, attr_name)
                if callable(attr):
                    return attr
        return None

    def get_shared_coded_tool_class(self, tool_name: str) -> str:
        """
        Get class of the shared coded tool

        :param tool_name: The name of the tool
        :return: The class of the coded tool
        """
        tool_info: Dict[str, Any] = self.toolbox_infos.get(tool_name)
        return tool_info.get("class")

    def get_tool_info(self, tool_name: str) -> Dict[str, Any]:
        """
        :param tool_name: The name of the tool.
        :return: The toolbox dictionary entry for the tool name
        """
        tool_info: Dict[str, Any] = self.toolbox_infos.get(tool_name)
        return tool_info
