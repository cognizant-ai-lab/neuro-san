
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

from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer


class RawAgentNetworkRestorer(AgentNetworkRestorer):
    """
    Same as AgentNetworkRestorer, except the standard commondefs/defaults/
    name-correction filter chain is skipped entirely.

    The resulting config is parsed from the HOCON/JSON source with includes
    resolved exactly as AgentNetworkRestorer does, but with no commondefs
    substitution, defaults injection, or name correction applied.

    This is useful for lint-style checks that need to see the document as
    the author wrote it, e.g. detecting a commondefs entry that is never
    referenced by any {replacement} token or bare value anywhere else in
    the file: once the standard filter chain runs, that evidence is gone,
    either replaced away or (if unused) simply absent from the result.
    """

    def filter_config(self, basis_config: Dict[str, Any], file_path: str = None) -> Dict[str, Any]:
        """
        :param basis_config: agent configuration dictionary, built or parsed from external sources
        :param file_path: The file path the config was read from. Unused here.
        :return: The basis_config, unmodified.
        """
        return basis_config
