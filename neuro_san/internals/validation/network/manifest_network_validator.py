
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
from neuro_san.internals.validation.network.keyword_network_validator import KeywordNetworkValidator
from neuro_san.internals.validation.network.missing_nodes_network_validator import MissingNodesNetworkValidator
from neuro_san.internals.validation.network.tool_name_network_validator import ToolNameNetworkValidator
from neuro_san.internals.validation.network.unreachable_nodes_network_validator import UnreachableNodesNetworkValidator
from neuro_san.internals.validation.network.url_network_validator import UrlNetworkValidator


class ManifestNetworkValidator(CompositeDictionaryValidator):
    """
    Implementation of CompositeDictionaryValidator interface that uses multiple specific validators
    to do some standard validation upon reading in an agent network description.
    """

    def __init__(self, external_network_names: List[str] = None, mcp_servers: List[str] = None):
        """
        Constructor

        :param external_network_names: A list of external network names
        :param mcp_servers: A list of MCP servers, as read in from a mcp_info.hocon file
        """
        validators: List[DictionaryValidator] = [
            # Note we do use the CyclesNetworkValidator here because cycles are actually OK.
            KeywordNetworkValidator(),
            MissingNodesNetworkValidator(),
            UnreachableNodesNetworkValidator(),
            # No ToolBoxNetworkValidator yet.
            ToolNameNetworkValidator(),
            UrlNetworkValidator(external_network_names, mcp_servers),
        ]
        super().__init__(validators)
