
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

import os

from pathlib import Path

from neuro_san import TOP_LEVEL_DIR
from neuro_san.internals.graph.activations.front_man_activation import FrontManActivation
from neuro_san.internals.graph.preppers.activation_prepper import ActivationPrepper
from neuro_san.internals.graph.preppers.branch_activation_prepper import BranchActivationPrepper
from neuro_san.internals.graph.preppers.class_activation_prepper import ClassActivationPrepper
from neuro_san.internals.graph.preppers.external_activation_prepper import ExternalActivationPrepper
from neuro_san.internals.graph.preppers.front_man_activation_prepper import FrontManActivationPrepper
from neuro_san.internals.graph.preppers.toolbox_activation_prepper import ToolboxActivationPrepper
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.interfaces.callable_activation import CallableActivation
from neuro_san.internals.interfaces.front_man import FrontMan
from neuro_san.internals.run_context.interfaces.run_context import RunContext


class ActivationFactory(AgentToolFactory):
    """
    A factory class for creating Activations of tools within the agent network graph.
    That is, this is where neuro-san tools are made real.
    """

    PREPPERS: List[ActivationPrepper] = [
        ExternalActivationPrepper(),
        ToolboxActivationPrepper(),
        ClassActivationPrepper(),
        BranchActivationPrepper(),
        FrontManActivationPrepper(),
    ]

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
            agent_tool_path = TOP_LEVEL_DIR.get_file_in_basis("coded_tools")

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
                pythonpath_split = pythonpath.split(os.pathsep)
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

        # Now, agent network name itself can contain "/" symbols (regardless of underlying OS)
        # in case of hierarchical agents structure. Replace those with "." as well.
        agent_network_path = self.agent_network.get_network_name().replace("/", ".")

        # Be sure the name of the agent (stem of the hocon file) is the
        # last piece to narrow down the path resolution further.
        if not agent_tool_path.endswith(agent_network_path):
            agent_tool_path = f"{agent_tool_path}.{agent_network_path}"

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
                                factory: AgentToolFactory = None,
                                invocation: str = None) -> CallableActivation:
        """
        Create an active node for an agent from its spec.
        This is how CallableActivations create other CallableActivations.

        :param parent_run_context: The RunContext of the agent calling this method
        :param parent_agent_spec: The spec of the agent calling this method.
        :param name: The name of the agent to get out of the registry
        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be an empty dictionary.
        :param arguments: A dictionary of arguments for the newly constructed agent
        :param factory: A factory that will be used to create the agent tool
        :param invocation: The invocation style of the activation.
        :return: The CallableActivation agent referred to by the name.
        """
        if factory is None:
            factory = self

        # Find the agent tool spec dictionary given the name
        agent_tool_spec: Dict[str, Any] = self.agent_network.get_agent_tool_spec(name)

        # Find the appropriate ActivationPrepper given the agent tool spec
        prepper: ActivationPrepper = None
        for candidate in self.PREPPERS:
            if candidate.is_applicable(agent_tool_spec):
                prepper = candidate
                break

        if prepper is None:
            raise ValueError(f"No activation handler found for {name} (tool spec: {agent_tool_spec})")

        # Prepare the activation
        agent_activation: CallableActivation = prepper.prepare_activation(
            name,
            agent_tool_spec,
            parent_agent_spec,
            arguments,
            sly_data,
            parent_run_context,
            factory,
            invocation
        )

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
