
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

from leaf_common.config.config_filter import ConfigFilter

from neuro_san.internals.interfaces.storage_class import StorageClass


class McpManifestDictConfigFilter(ConfigFilter):
    """
    Implementation of the ConfigFilter interface that reads the contents
    of a single manifest configuration dictionary for an agent networks/registry,
    making sure the mcp setting is consistent with the rest of the manifest dictionary.
    """

    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filters the given basis config.

        :param basis_config: The config dictionary to act as the basis
                for filtering
        :return: A config dictionary, potentially modified as per the
                policy encapsulated by the implementation
        """

        # MCP designated entries are considered public by default.
        if "mcp" not in basis_config:
            basis_config["mcp"] = False
        if basis_config["mcp"]:
            basis_config[StorageClass.PUBLIC] = True

        return basis_config
