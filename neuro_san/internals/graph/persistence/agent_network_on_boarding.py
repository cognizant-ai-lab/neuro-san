
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

from logging import getLogger
from logging import Logger

from leaf_common.config.config_filter import ConfigFilter
from leaf_common.validation.composite_dictionary_validator import CompositeDictionaryValidator
from leaf_common.validation.dictionary_validator import DictionaryValidator

from neuro_san.internals.graph.filters.network_config_filter_chain import NetworkConfigFilterChain
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.validation.network.fully_qualified_class_network_validator import \
    FullyQualifiedClassNetworkValidator
from neuro_san.internals.validation.network.manifest_network_validator import ManifestNetworkValidator


class AgentNetworkOnBoarding(ConfigFilter, DictionaryValidator):
    """
    Perform common on-boarding tasks for an agent network.
    """

    def __init__(self, network_name: str = None,
                 require_fully_qualified_classes: bool = False,
                 external_network_names: List[str] = None,
                 mcp_servers: List[str] = None):
        """
        Constructor

        :param network_name: The agent network name for diagnostic log lines
        :param require_fully_qualified_classes: When True, every CodedTool "class" reference
                    must be fully-qualified. Default is False.
        :param external_network_names: A list of external network names
        :param mcp_servers: A list of MCP servers, as read in from a mcp_info.hocon file
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.filter: ConfigFilter = NetworkConfigFilterChain()

        # On-boarding runs the standard manifest validation plus checks that apply
        # only to networks that do not come from the manifest.
        validators: List[DictionaryValidator] = [
            ManifestNetworkValidator(external_network_names, mcp_servers, network_name),
        ]
        if require_fully_qualified_classes:
            validators.append(FullyQualifiedClassNetworkValidator(network_name=network_name))
        self.validator: DictionaryValidator = CompositeDictionaryValidator(validators)

    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filters the given basis config.

        Ideally this would be a Pure Function in that it would not
        modify the caller's arguments so that the caller has a chance
        to decide whether to take any changes returned.

        :param basis_config: The config dictionary to act as the basis
                for filtering
        :return: A config dictionary, potentially modified as per the
                policy encapsulated by the implementation
        """
        filtered: Dict[str, Any] = self.filter.filter_config(basis_config)
        return filtered

    def validate(self, candidate: Dict[str, Any]) -> List[str]:
        """
        Validate the given dictionary

        :param candidate: The dictionary to validate
        :return: A list of error messages
        """
        errors: List[str] = self.validator.validate(candidate)
        return errors

    def on_board(self, agent_network: AgentNetwork) -> AgentNetwork:
        """
        Perform on-boarding tasks for the given agent network.

        :param agent_network: The agent network to on-board
        :return: The agent network, potentially modified as per the policy encapsulated by the implementation,
                 or None if there were validation errors.
        """
        # Filter first
        existing_config: Dict[str, Any] = agent_network.get_config()
        filtered_config: Dict[str, Any] = self.filter_config(existing_config)

        # Validate next
        network_name: str = agent_network.get_network_name()
        errors: List[str] = self.validate(filtered_config)
        if len(errors) > 0:
            self.logger.error("Agent network %s has validation errors. Errors: %s", network_name, errors)
            return None

        vetted: AgentNetwork = AgentNetwork(filtered_config, network_name)
        return vetted
