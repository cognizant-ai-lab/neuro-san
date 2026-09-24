
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

    The "mcp" key of a manifest entry is either a boolean or a dictionary, like
    "periodic". Whatever the author wrote, this filter leaves it as a dictionary
    so that downstream code reads one shape:

        {
            "enable": <bool>,   # serve the network as an MCP tool
            "name": <str>       # the tool name to advertise, or None to derive it
        }

        "mcp" absent        -> {"enable": False, "name": None}
        "mcp": <bool>       -> {"enable": <bool>, "name": None}
        "mcp": {...}        -> the dictionary merged onto {"enable": True, "name": None},
                               so giving the dictionary at all switches the tool on
                               unless it says "enable": false.

    "enable" True implies "public" True: a tool nobody can reach is pointless.
    A "name" that is not a non-empty string is dropped with a warning, so the
    tool name gets derived from the network name instead. The name is not
    validated here; RegistryManifestRestorer does that once, on the final value.
    Unknown keys inside the dictionary are kept, so MCP settings can grow.
    """

    MCP_KEY: str = "mcp"
    ENABLE_KEY: str = "enable"
    NAME_KEY: str = "name"

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
        mcp_settings: Dict[str, Any] = self.normalize_mcp_settings(basis_config.get(self.MCP_KEY))
        basis_config[self.MCP_KEY] = mcp_settings

        # MCP designated entries are considered public by default.
        if mcp_settings.get(self.ENABLE_KEY):
            basis_config[StorageClass.PUBLIC] = True

        return basis_config

    def normalize_mcp_settings(self, value: Any) -> Dict[str, Any]:
        """
        Turns whatever the manifest author wrote for "mcp" into the settings dictionary.

        :param value: The raw "mcp" value from the manifest entry: None when absent,
                      a boolean, or a dictionary of settings.
        :return: A new dictionary with at least the "enable" and "name" keys
        """
        settings: Dict[str, Any] = {
            self.ENABLE_KEY: False,
            self.NAME_KEY: None
        }
        if value is None:
            # Absent: dictionary entries are not MCP tools unless they say so.
            return settings

        if isinstance(value, bool):
            settings[self.ENABLE_KEY] = value
            return settings

        if not isinstance(value, dict):
            self.logger.warning("Manifest entry for %s in file %s has an \"mcp\" value that is neither " +
                                "a boolean nor a dictionary (%s). Treating it as false.",
                                self.agent_network, self.manifest_file, repr(value))
            return settings

        # Writing the dictionary out is itself a request to serve the tool,
        # so "enable" defaults to True here. Shallow-merge so that unknown
        # keys survive, the same way "periodic" settings are merged.
        settings[self.ENABLE_KEY] = True
        settings.update(value)

        enable: Any = settings.get(self.ENABLE_KEY)
        if not isinstance(enable, bool):
            self.logger.warning("Manifest entry for %s in file %s has an \"mcp\" \"enable\" value that is " +
                                "not a boolean (%s). Reading it as %s.",
                                self.agent_network, self.manifest_file, repr(enable), bool(enable))
            settings[self.ENABLE_KEY] = bool(enable)

        name: Any = settings.get(self.NAME_KEY)
        if name is not None and not (isinstance(name, str) and name):
            # Drop the bad value rather than keep it: downstream code treats any
            # present name as the name to advertise, and a non-string there would
            # surface as a confusing failure much later, at tools/list time.
            self.logger.warning("Manifest entry for %s in file %s has an \"mcp\" \"name\" that is not a " +
                                "non-empty string (%s). Ignoring it; if the entry is an MCP tool, its " +
                                "tool name will be derived from the network name.",
                                self.agent_network, self.manifest_file, repr(name))
            settings[self.NAME_KEY] = None

        return settings
