
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

from logging import getLogger
from logging import Logger

from leaf_common.config.config_filter import ConfigFilter

from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.graph.persistence.manifest_dict_filter_chain import ManifestDictFilterChain


class ManifestDictConfigFilter(ConfigFilter):
    """
    Implementation of the ConfigFilter interface that reads the contents
    of a single manifest file for agent networks/registries, converting
    any Easy boolean values to a specific dictionary.
    """

    MCP_DEFAULT_MODE: bool = True

    def __init__(self, manifest_file: str):
        """
        Constructor

        :param manifest_file: The name of the manifest file we are processing for logging purposes
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.manifest_file: str = manifest_file

    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Filters the given basis config.

        Manifest entries can either be a boolean or a dictionary.
        This translates any boolean entries into all dictionary form:
            {
                "serve": <bool>,
                "public": <bool>,
            }

        :param basis_config: The config dictionary to act as the basis
                for filtering
        :return: A config dictionary, potentially modified as per the
                policy encapsulated by the implementation
        """

        filtered: Dict[str, Dict[str, Any]] = {}

        for key, value in basis_config.items():

            # Default template
            expanded_value: Dict[str, Any] = {
                "serve": True,
                StorageClass.PUBLIC: True,
                "mcp": self.MCP_DEFAULT_MODE,
                "periodic": False
            }

            # Traditional, easy entry in a manifest file.
            if isinstance(value, bool):
                if not value:
                    updated_value: Dict[str, Any] = {
                        "serve": False,
                        StorageClass.PUBLIC: False
                    }
                    expanded_value.update(updated_value)
            elif isinstance(value, Dict):
                expanded_value = value
            else:
                self.logger.warning("Manifest entry for %s in file %s " +
                                    "must be either a boolean or a dictionary. Skipping.",
                                    key, self.manifest_file)
                continue

            # Apply the filter chain to the basis dictionary
            entry_filter_chain = ManifestDictFilterChain(self.manifest_file, key)
            filtered[key] = entry_filter_chain.filter_config(expanded_value)

        return filtered
