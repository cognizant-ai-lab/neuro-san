
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

from leaf_common.config.dictionary_overlay import DictionaryOverlay

from neuro_san.internals.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.interfaces.callable_activation import CallableActivation
from neuro_san.internals.run_context.interfaces.run_context import RunContext


class ActivationPrepper:
    """
    Interface for policy objects which prepare a particular kind of activation
    All implementations must be stateless.
    """

    def is_applicable(self, agent_tool_spec: Dict[str, Any]) -> bool:
        """
        :param agent_tool_spec: the agent tool spec dictionary. Can be None for external agents.
        :return: True if this ActivationPrepper is applicable to the given agent tool spec
        """
        raise NotImplementedError

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
        raise NotImplementedError

    def merge_args(self, llm_args: Dict[str, Any], agent_tool_spec: Dict[str, Any]) -> Dict[str, Any]:
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
