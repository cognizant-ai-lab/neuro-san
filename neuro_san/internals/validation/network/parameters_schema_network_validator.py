
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

from leaf_common.validation.dictionary_validator import DictionaryValidator
from leaf_common.validation.composite_dictionary_validator import CompositeDictionaryValidator

from neuro_san.internals.graph.filters.network_config_filter_chain import NetworkConfigFilterChain
from neuro_san.internals.validation.network.pydantic_parameters_network_validator import \
    PydanticParametersNetworkValidator
from neuro_san.internals.validation.network.semantic_parameters_network_validator import \
    SemanticParametersNetworkValidator


class ParametersSchemaNetworkValidator(CompositeDictionaryValidator):
    """
    CompositeDictionaryValidator that assembles the two independent
    parameter-validation phases:

      Phase 1 – PydanticParametersNetworkValidator
        Structural validation via BaseModelDictionaryConverter.

      Phase 2 – SemanticParametersNetworkValidator
        Semantic checks pydantic cannot detect (nested 'parameters'
        keys, undefined required references).
    """

    def __init__(self, network_name: str = None):
        """
        Constructor

        :param network_name: The agent network name for diagnostic log lines
        """
        validators: List[DictionaryValidator] = [
            PydanticParametersNetworkValidator(network_name=network_name),
            SemanticParametersNetworkValidator(network_name=network_name),
        ]
        super().__init__(validators)

    # Overrides CompositeDictionaryValidator.validate
    def validate(self, candidate: Dict[str, Any]) -> List[str]:
        """
        Resolve the config once, then run both parameter phases on it.

        The parameter validators need fully-resolved configs (commondefs
        substitution, defaults injection, name correction). Filtering here -
        rather than inside each leaf validator - means the filter chain runs
        a single time for both phases instead of once per validator, which
        matters when this composite is itself nested inside the larger
        ManifestNetworkValidator.

        :param candidate: The agent network or name -> spec dictionary to validate
        :return: A list of error messages
        """
        if not candidate:
            return super().validate(candidate)

        filtered: Dict[str, Any] = NetworkConfigFilterChain().filter_config(candidate)
        return super().validate(filtered)
