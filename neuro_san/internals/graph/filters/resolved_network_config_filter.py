
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

from copy import deepcopy

from leaf_common.config.config_filter import ConfigFilter

from neuro_san.internals.graph.filters.network_config_filter_chain import NetworkConfigFilterChain


class ResolvedNetworkConfigFilter(ConfigFilter):
    """
    ConfigFilter that turns an agent network spec into its fully resolved,
    self-contained form: the standard NetworkConfigFilterChain is applied and
    the consumed "commondefs" block is removed from the result.

    Networks loaded from hocon files get the chain applied in
    AgentNetworkRestorer.filter_config().  Specs that arrive as plain
    dictionaries assembled in code (the Reservations API for temporary
    networks) do not, so without this step none of the top-level defaults that
    DefaultsConfigFilter distributes (llm_config, verbose, max_steps,
    max_execution_seconds, max_attempts, error_formatter, error_fragments and
    the front-man-only sly_data_schema) is ever applied to their agents, and no
    commondefs substitution happens.  Most visibly, the "global" top-level
    sly_data_schema that a deployment's llm_config.hocon defines alongside
    llm_config would never be merged into the front man's
    function.sly_data_schema, so the /function endpoint of a temporary network
    would not tell clients that it needs BYOK keys in sly_data.llm_config.

    Two properties make the output safe to persist and to filter again:

    * The result is always a copy.  The chain only copies when there are tools
      to work on and otherwise hands back the caller's own dictionary; this
      filter copies in that case too, so neither the commondefs removal nor
      whatever the caller does with the result (e.g. a storage writer that
      injects metadata) can reach the input.
    * The result is a fixed point of this filter.  The commondefs filters
      resolve one level of substitution per pass and never strip the block
      themselves, so a spec that kept it would come out different on every
      pass.  With the block removed, the remaining filters leave an already
      resolved spec unchanged, which is what lets the reservation readers run
      this filter again on a spec the writer already resolved.

    Used by ExpiringAgentNetworkStorage before a reservation spec is stored and
    by the S3 and local reservation readers when a spec is loaded.
    """

    def __init__(self) -> None:
        """
        Constructor
        """
        super().__init__()
        self.filter_chain: ConfigFilter = NetworkConfigFilterChain()

    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolves the given agent network spec.

        :param basis_config: The agent network spec dictionary as deployed.
                Never modified.
        :return: A new, fully resolved spec dictionary with the "commondefs"
                block removed.  None if basis_config is None.
        """
        if basis_config is None:
            # Every filter in the chain passes None through untouched, so this is the
            # contract made explicit rather than protection against a crash.
            return None

        resolved: Dict[str, Any] = self.filter_chain.filter_config(basis_config)
        if resolved is basis_config:
            # The chain only copies when there are tools to work on; for anything else
            # it hands back the caller's own dict.  Copy it ourselves so that the removal
            # below, and anything the caller does with the result, cannot touch the input.
            resolved = deepcopy(basis_config)

        if isinstance(resolved, dict) and "commondefs" in resolved:
            # The chain has consumed this block.  Leaving it in would make a second pass
            # substitute again, so the output would not be a fixed point.
            del resolved["commondefs"]

        return resolved
