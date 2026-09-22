
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


class McpManifestDictConfigFilter(ConfigFilter):
    """
    Implementation of the ConfigFilter interface that reads the contents
    of a single manifest configuration dictionary for an agent networks/registry,
    making sure the mcp settings are consistent with the rest of the manifest dictionary.

    Two keys are handled:
        "mcp"       - boolean; defaults to False. True implies "public" is True.
        "mcp_name"  - optional string naming the tool the network is advertised as
                      over MCP. A usable value implies "mcp" (and therefore "public")
                      is True, unless the entry explicitly says "mcp": false, which
                      wins and leaves the name without effect (warned about).
                      Absent means the tool name is derived from the network
                      name later, by RegistryManifestRestorer, which is also where the
                      name is validated so that the check happens exactly once with
                      the final value.
    """

    def __init__(self, manifest_file: str = None, agent_network: str = None) -> None:
        """
        Constructor

        :param manifest_file: The name of the manifest file we are processing for logging purposes
        :param agent_network: The name of the agent network for logging purposes
        """
        super().__init__()
        self.manifest_file: str = manifest_file
        self.agent_network: str = agent_network
        self.logger: Logger = getLogger(self.__class__.__name__)

    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filters the given basis config.

        :param basis_config: The config dictionary to act as the basis
                for filtering
        :return: A config dictionary, potentially modified as per the
                policy encapsulated by the implementation
        """

        # MCP designated entries are considered public by default.
        # Whether "mcp" was written out matters below: an explicit false is an
        # opt-out that an "mcp_name" must not silently undo.
        mcp_was_given: bool = "mcp" in basis_config
        if not mcp_was_given:
            basis_config["mcp"] = False
        if basis_config["mcp"]:
            basis_config[StorageClass.PUBLIC] = True

        if "mcp_name" in basis_config:
            mcp_name: Any = basis_config.get("mcp_name")
            if isinstance(mcp_name, str) and mcp_name:
                if mcp_was_given and not basis_config["mcp"]:
                    # The name is left in place, harmless, for when "mcp" is switched on.
                    self.logger.warning("Manifest entry for %s in file %s sets \"mcp\": false, so its " +
                                        "\"mcp_name\" %s has no effect. Remove \"mcp\": false to advertise " +
                                        "the network as an MCP tool under that name.",
                                        self.agent_network, self.manifest_file, repr(mcp_name))
                else:
                    # Naming the tool only makes sense when the network is served as one,
                    # so a usable mcp_name switches "mcp" on the same way "mcp" switches
                    # "public" on above.
                    basis_config["mcp"] = True
                    basis_config[StorageClass.PUBLIC] = True
            else:
                # Drop the bad value rather than keep it: downstream code treats any
                # present mcp_name as the name to advertise, and a non-string there
                # would surface as a confusing failure much later, at tools/list time.
                self.logger.warning("Manifest entry for %s in file %s has an \"mcp_name\" that is not a " +
                                    "non-empty string (%s). Ignoring it; if the entry is an MCP tool, its " +
                                    "tool name will be derived from the network name.",
                                    self.agent_network, self.manifest_file, repr(mcp_name))
                del basis_config["mcp_name"]

        return basis_config
