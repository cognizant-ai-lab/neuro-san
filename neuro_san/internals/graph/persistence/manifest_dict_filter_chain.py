
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

from leaf_common.config.config_filter_chain import ConfigFilterChain

from neuro_san.internals.graph.persistence.mcp_manifest_dict_config_filter import McpManifestDictConfigFilter
from neuro_san.internals.graph.persistence.periodic_manifest_dict_config_filter import PeriodicManifestDictConfigFilter


class ManifestDictFilterChain(ConfigFilterChain):
    """
    ConfigFilterChain for manifest dictionary entries.
    """

    def __init__(self, manifest_file: str, agent_network: str):
        """
        Constructor

        :param manifest_file: The name of the manifest file we are processing for logging purposes
        :param agent_network: The name of the agent network for logging purposes
        """
        super().__init__()

        # Order matters
        self.register(McpManifestDictConfigFilter())
        self.register(PeriodicManifestDictConfigFilter(manifest_file, agent_network))
