
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
from leaf_common.config.config_filter_chain import ConfigFilterChain

from neuro_san.internals.graph.filters.defaults_config_filter import DefaultsConfigFilter
from neuro_san.internals.graph.filters.dictionary_common_defs_config_filter \
    import DictionaryCommonDefsConfigFilter
from neuro_san.internals.graph.filters.name_correction_config_filter import NameCorrectionConfigFilter
from neuro_san.internals.graph.filters.string_common_defs_config_filter import StringCommonDefsConfigFilter


class NetworkConfigFilterChain(ConfigFilter):
    """
    A reusable ConfigFilter that applies the standard agent network
    filter chain: commondefs substitution, defaults injection, and
    name correction.

    This is the canonical ordering of filters for any agent network
    config dictionary.  Both AgentNetworkRestorer and the validation
    layer use this to ensure configs are fully resolved before
    further processing.
    """

    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param basis_config: Raw agent network config dictionary
        :return: A fully resolved config dictionary
        """
        filter_chain = ConfigFilterChain()
        filter_chain.register(DictionaryCommonDefsConfigFilter())
        filter_chain.register(StringCommonDefsConfigFilter())
        filter_chain.register(DefaultsConfigFilter())
        filter_chain.register(NameCorrectionConfigFilter())

        config: Dict[str, Any] = filter_chain.filter_config(basis_config)
        return config
