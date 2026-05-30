
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
from typing import List

from neuro_san.internals.interfaces.dictionary_validator import DictionaryValidator
from neuro_san.internals.validation.common.composite_dictionary_validator import CompositeDictionaryValidator
from neuro_san.internals.validation.network.cycles_network_validator import CyclesNetworkValidator
from neuro_san.internals.validation.network.missing_nodes_network_validator import MissingNodesNetworkValidator
from neuro_san.internals.validation.network.tools_shape_validator import ToolsShapeValidator
from neuro_san.internals.validation.network.unreachable_nodes_network_validator import UnreachableNodesNetworkValidator


class StructureNetworkValidator(CompositeDictionaryValidator):
    """
    Implementation of CompositeDictionaryValidator interface that uses multiple specific validators
    to do some standard validation for topological issues.
    This gets used by agent network designer.
    """

    def __init__(self):
        """
        Constructor
        """
        validators: List[DictionaryValidator] = [
            ToolsShapeValidator(),
            CyclesNetworkValidator(),
            MissingNodesNetworkValidator(),
            UnreachableNodesNetworkValidator(),
        ]
        super().__init__(validators)
