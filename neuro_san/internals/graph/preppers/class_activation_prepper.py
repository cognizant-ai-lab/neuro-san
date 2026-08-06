
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

from neuro_san.internals.graph.activations.class_activation import ClassActivation
from neuro_san.internals.graph.preppers.activation_prepper import ActivationPrepper
from neuro_san.internals.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.interfaces.callable_activation import CallableActivation
from neuro_san.internals.run_context.interfaces.run_context import RunContext


class ClassActivationPrepper(ActivationPrepper):
    """
    ActivationPrepper implementation for ClassActivations (coded tools).
    """

    def is_applicable(self, agent_tool_spec: Dict[str, Any]) -> bool:
        """
        :param agent_tool_spec: the agent tool spec dictionary
        :return: True if this ActivationPrepper is applicable to the given agent tool spec
        """
        return agent_tool_spec.get("function") is not None and agent_tool_spec.get("class") is not None

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def prepare_activation(self,
                           name: str,
                           agent_tool_spec: Dict[str, Any],
                           parent_agent_spec: Dict[str, Any],
                           arguments: Dict[str, Any],
                           sly_data: Dict[str, Any],
                           parent_run_context: RunContext,
                           factory: AgentToolFactory,
                           invocation: str) -> CallableActivation:
        """
        Assuming that is_applicable() has already been vetted, this method prepares a CallableActivation
        object for the given agent tool spec.

        :param name: the name of the agent tool
        :param agent_tool_spec: the agent tool spec dictionary
        :param parent_agent_spec: the parent agent spec dictionary
        :param arguments: the arguments dictionary
        :param sly_data: the sly data dictionary
        :param parent_run_context: the parent run context
        :param factory: the agent tool factory
        :param invocation: the invocation string ("chatbot" or "event")
        :return: a CallableActivation
        """
        use_args: Dict[str, Any] = self.merge_args(arguments, agent_tool_spec)
        return ClassActivation(parent_run_context, factory, use_args, agent_tool_spec, sly_data)
