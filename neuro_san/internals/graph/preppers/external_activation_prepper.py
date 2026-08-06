
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

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.graph.activations.external_activation import ExternalActivation
from neuro_san.internals.graph.preppers.activation_prepper import ActivationPrepper
from neuro_san.internals.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.interfaces.callable_activation import CallableActivation
from neuro_san.internals.messages.sly_data_redactor import SlyDataRedactor
from neuro_san.internals.run_context.interfaces.run_context import RunContext
from neuro_san.internals.run_context.utils.external_agent_parsing import ExternalAgentParsing


class ExternalActivationPrepper(ActivationPrepper):
    """
    ActivationPrepper implementation for external agent networks.
    """

    def is_applicable(self, agent_tool_spec: Dict[str, Any]) -> bool:
        """
        :param agent_tool_spec: the agent tool spec dictionary
        :return: True if this ActivationPrepper is applicable to the given agent tool spec
        """
        applicable: bool = agent_tool_spec is None
        return applicable

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
                                              allow_from_downstream, invocation)
        return agent_activation

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
