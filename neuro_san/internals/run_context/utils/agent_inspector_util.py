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

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.run_context.interfaces.agent_network_inspector import AgentNetworkInspector


class AgentInspectorUtil:
    """
    Utility class for answering questions about an agent network through its AgentNetworkInspector.
    """

    @staticmethod
    def get_llm_config_sly_data_schema(inspector: AgentNetworkInspector) -> Dict[str, Any]:
        """
        Gets the llm_config portion of the sly_data_schema that the agent network's front man declares.
        This describes the keys clients are expected to send in sly_data.llm_config.

        :param inspector: The AgentNetworkInspector instance.  Common internal implementations of
                        AgentNetworkInspector include AgentNetwork, AgentToolRegistry.
        :return: The schema of the llm_config property of the front man's sly_data_schema,
                or None when there is no inspector or the front man does not declare one.
        :raises ValueError: When the network has no valid front man
        """
        if inspector is None:
            return None

        front_man: str = inspector.find_front_man()
        front_man_spec: Dict[str, Any] = inspector.get_agent_tool_spec(front_man)

        extractor = DictionaryExtractor(front_man_spec)
        llm_config_schema: Dict[str, Any] = extractor.get("function.sly_data_schema.properties.llm_config")
        return llm_config_schema
