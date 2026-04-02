
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
from __future__ import annotations

from typing import Any
from typing import Dict

from neuro_san.internals.graph.interfaces.callable_activation import CallableActivation
from neuro_san.internals.run_context.interfaces.run_context import RunContext


class AgentToolFactory:
    """
    Interface describing a factory that creates agent tools.
    Having this interface breaks some circular dependencies.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def create_agent_activation(self,
                                parent_run_context: RunContext,
                                parent_agent_spec: Dict[str, Any],
                                name: str,
                                sly_data: Dict[str, Any],
                                arguments: Dict[str, Any] = None,
                                factory: AgentToolFactory = None,
                                invocation: str = None) -> CallableActivation:
        """
        Create an active node for an agent from its spec.

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
        raise NotImplementedError

    def get_config(self) -> Dict[str, Any]:
        """
        :return: The entire config dictionary given to the instance.
        """
        raise NotImplementedError

    def get_agent_tool_path(self) -> str:
        """
        :return: The path under which tools for this registry should be looked for.
        """
        raise NotImplementedError

    def get_name_from_spec(self, agent_spec: Dict[str, Any]) -> str:
        """
        :param agent_spec: A single agent to register
        :return: The agent name as per the spec
        """
        raise NotImplementedError
