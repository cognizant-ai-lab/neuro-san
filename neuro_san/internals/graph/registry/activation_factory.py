
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

import os

from pathlib import Path

from leaf_common.config.dictionary_overlay import DictionaryOverlay
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.graph.activations.branch_activation import BranchActivation
from neuro_san.internals.graph.activations.class_activation import ClassActivation
from neuro_san.internals.graph.activations.external_activation import ExternalActivation
from neuro_san.internals.graph.activations.front_man_activation import FrontManActivation
from neuro_san.internals.graph.activations.sly_data_redactor import SlyDataRedactor
from neuro_san.internals.graph.activations.toolbox_activation import ToolboxActivation
from neuro_san.internals.graph.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.graph.interfaces.callable_activation import CallableActivation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.front_man import FrontMan
from neuro_san.internals.run_context.interfaces.run_context import RunContext
from neuro_san.internals.run_context.utils.external_agent_parsing import ExternalAgentParsing
from neuro_san.internals.utils.file_of_class import FileOfClass


class ActivationFactory(AgentToolFactory):
    """
    A factory class for creating Activations of tools within the agent network graph.
    That is, this is where neuro-san tools are made real.
    """

    def __init__(self, agent_network: AgentNetwork):
        """
        Constructor

        :param agent_network: The AgentNetwork this factory will be basing its information on
        """
        self.agent_network: AgentNetwork = agent_network
        self.agent_tool_path: str = self._determine_agent_tool_path()

    def _determine_agent_tool_path(self) -> str:
        """
        Policy for determining where tool source should be looked for
        when resolving references to coded tools.

        :return: the agent tool path to use for source resolution.
        """
        # Try the env var first if nothing to start with
        agent_tool_path: str = os.environ.get("AGENT_TOOL_PATH")

        # Try reach-around directory if still nothing to start with
        if agent_tool_path is None:
            file_of_class = FileOfClass(__file__, "../../../coded_tools")
            agent_tool_path = file_of_class.get_basis()

        # If we are dealing with file paths, convert that to something resolvable
        if agent_tool_path.find(os.sep) >= 0:

            # Find the best of many resolution paths in the PYTHONPATH
            resolved_tool_path: str = str(Path(agent_tool_path).resolve())
            best_path = ""
            pythonpath: str = os.environ.get("PYTHONPATH")
            if pythonpath is None:
                # Trust what we have already
                best_path = agent_tool_path
            else:
                pythonpath_split = pythonpath.split(":")
                for one_path in pythonpath_split:
                    resolved_path: str = str(Path(one_path).resolve())
                    if resolved_tool_path.startswith(resolved_path) and \
                            len(resolved_path) > len(best_path):
                        best_path = resolved_path

            if len(best_path) == 0:
                raise ValueError(f"No reasonable agent tool path found in PYTHONPATH for {agent_tool_path}")

            # Find the path beneath the python path
            path_split = resolved_tool_path.split(best_path)
            if len(path_split) < 2:
                raise ValueError("""
Cannot find tool path for {agent_tool_path} in PYTHONPATH.
Check to be sure your value for PYTHONPATH includes where you expect where your coded tools live.
""")
            resolve_path = path_split[1]

            # Replace separators with python delimiters for later resolution
            agent_tool_path = resolve_path.replace(os.sep, ".")

            # Remove any leading .s
            while agent_tool_path.startswith("."):
                agent_tool_path = agent_tool_path[1:]

        # Be sure the name of the agent (stem of the hocon file) is the
        # last piece to narrow down the path resolution further.
        if not agent_tool_path.endswith(self.agent_network.get_network_name()):
            agent_tool_path = f"{agent_tool_path}.{self.agent_network.get_network_name()}"

        return agent_tool_path

    def get_agent_tool_path(self) -> str:
        """
        :return: The path under which tools for this registry should be looked for.
        """
        return self.agent_tool_path

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def create_agent_activation(self, parent_run_context: RunContext,
                                parent_agent_spec: Dict[str, Any],
                                name: str,
                                sly_data: Dict[str, Any],
                                arguments: Dict[str, Any] = None,
                                factory: AgentToolFactory = None) -> CallableActivation:
        """
        Create an active node for an agent from its spec.
        This is how CallableActivations create other CallableActivations.

        :param parent_run_context: The RunContext of the agent calling this method
        :param parent_agent_spec: The spec of the agent calling this method.
        :param name: The name of the agent to get out of the registry
        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be an empty dictionary.
        :param arguments: A dictionary of arguments for the newly constructed agent
        :return: The CallableActivation agent referred to by the name.
        """
        if factory is None:
            factory = self

        agent_activation: CallableActivation = None

        agent_tool_spec: Dict[str, Any] = self.agent_network.get_agent_tool_spec(name)
        if agent_tool_spec is None:

            if not ExternalAgentParsing.is_external_agent(name):
                raise ValueError(f"No agent_tool_spec for {name}")

            # For external tools, we want to redact the sly data based on
            # the calling/parent's agent specs.
            redacted_sly_data: Dict[str, Any] = self._redact_sly_data(parent_run_context, sly_data)

            # Get the spec for allowing upstream data
            extractor = DictionaryExtractor(parent_agent_spec)
            empty = {}
            allow_from_downstream: Dict[str, Any] = extractor.get("allow.from_downstream", empty)

            agent_activation = ExternalActivation(parent_run_context, factory, name, arguments, redacted_sly_data,
                                                  allow_from_downstream)
            return agent_activation

        # Merge the arguments coming in from the LLM with those that were specified
        # in the hocon file for the agent.
        use_args: Dict[str, Any] = self._merge_args(arguments, agent_tool_spec)

        if agent_tool_spec.get("toolbox") is not None:
            # If a toolbox is in the spec, this is a shared coded tool where tool's description and
            # args schema are defined in either AGENT_TOOLBOX_INFO_FILE or toolbox_info.hocon.
            agent_activation = ToolboxActivation(parent_run_context, factory, use_args, agent_tool_spec, sly_data)
            return agent_activation

        if agent_tool_spec.get("function") is not None:
            # If we have a function in the spec, the agent has arguments
            # it wants to be called with.
            if agent_tool_spec.get("class") is not None:
                # Agent specifically requested a python class to be run,
                # and tool's description and args schema are defined in agent network hocon.
                agent_activation = ClassActivation(parent_run_context, factory, use_args, agent_tool_spec, sly_data)
            else:
                agent_activation = BranchActivation(parent_run_context, factory, use_args, agent_tool_spec, sly_data)
        else:
            # Get the tool to call from the spec.
            agent_activation = FrontManActivation(parent_run_context, factory, agent_tool_spec, sly_data)

        return agent_activation

    def create_front_man(self,
                         sly_data: Dict[str, Any] = None,
                         parent_run_context: RunContext = None,
                         factory: AgentToolFactory = None) -> FrontMan:
        """
        Find and create the FrontMan for DataDrivenChat

        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be an empty dictionary.
        :param parent_run_context: A RunContext instance
        :param factory: An optional extra parameter at this ActivationFactory level to provide
                    the correct object reference for factory scope/lifetime issues.
        """
        if factory is None:
            factory = self

        front_man_name: str = self.agent_network.find_front_man()

        agent_tool_spec: Dict[str, Any] = self.agent_network.get_agent_tool_spec(front_man_name)
        front_man = FrontManActivation(parent_run_context, factory, agent_tool_spec, sly_data)
        return front_man

    def get_config(self) -> Dict[str, Any]:
        """
        :return: The entire config dictionary given to the instance.
        """
        return self.agent_network.get_config()

    def get_name_from_spec(self, agent_spec: Dict[str, Any]) -> str:
        """
        :param agent_spec: A single agent to register
        :return: The agent name as per the spec
        """
        return self.agent_network.get_name_from_spec(agent_spec)

    def _merge_args(self, llm_args: Dict[str, Any], agent_tool_spec: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges the args specified by the llm with "hard-coded" args specified in the agent spec.
        Hard-coded args win over llm-specified args if both are defined.
        If you want the llm args to win out over the hard-coded args, use a default for
        the function spec instead of the hard-coded args.

        :param llm_args: argument dictionary that the LLM wants
        :param agent_tool_spec: The dictionary representing the spec registered agent
        """
        config_args: Dict[str, Any] = agent_tool_spec.get("args")
        if config_args is None:
            # Nothing to override
            return llm_args

        overlay = DictionaryOverlay()
        merged_args: Dict[str, Any] = overlay.overlay(llm_args, config_args)
        return merged_args

    def _redact_sly_data(self, parent_run_context: RunContext, sly_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Redact the sly_data based on the agent spec associated with the parent run context

        :param parent_run_context: The parent run context of the tool to be created.
        :param sly_data: The internal representation of the sly_data to be redacted
        :return: A new sly_data dictionary, redacted as per the parent spec
        """
        parent_spec: Dict[str, Any] = None
        if parent_run_context is not None:
            parent_spec = parent_run_context.get_agent_tool_spec()

        redactor = SlyDataRedactor(parent_spec, config_keys=["allow.sly_data", "allow.to_downstream.sly_data"])
        redacted: Dict[str, Any] = redactor.filter_config(sly_data)
        return redacted
