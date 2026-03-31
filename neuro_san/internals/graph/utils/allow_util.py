
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
from typing import List
from typing import Union

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.run_context.interfaces.agent_network_inspector import AgentNetworkInspector


class AllowUtil:
    """
    Utility class for handling questions about AgentNetwork allow blocks.
    """

    @staticmethod
    def is_allowed(inspector: AgentNetworkInspector, allow_key: str, deeper_keys: List[str] = None) -> bool:
        """
        Check if the agent network allows the given key on any one of its agent nodes.

        :param inspector: The AgentNetworkInspector instance.  Common internal implementations of
                        AgentNetworkInspector include AgentNetwork, AgentToolRegistry.
        :param allow_key: The key to check in the allow dictionary.
        :param deeper_keys: A list of keys to look deeper in the agent spec.

        :return: True if the key is present and true somewhere in the agent network.
                 False otherwise.
        """
        allow: bool = False

        if inspector is None or allow_key is None:
            return allow

        # Get the list of tools to look for
        config: Dict[str, Any] = inspector.get_config()
        tools: List[Dict[str, Any]] = []
        tools = config.get("tools", tools)

        # Loop through each of the tools/agents
        empty: Dict[str, Any] = {}
        agent_spec: Dict[str, Any] = empty
        for agent_spec in tools:
            allow = AllowUtil.is_allowed_in_agent_spec(agent_spec, allow_key, deeper_keys)
            if allow:
                return True

        return allow

    @staticmethod
    def is_allowed_in_agent_spec(agent_spec: Dict[str, Any], allow_key: str, deeper_keys: List[str] = None) -> bool:
        """
        Check if the agent spec allows the given key.
        Will also search each of the deeper_keys and can treat each value as a list to inspect as well
        (ala middleware).

        :param agent_spec: The agent spec to check.
        :param allow_key: The key to check in the allow dictionary.
        :param deeper_keys: A list of keys to look deeper in the agent spec.

        :return: True if the key is present and true somewhere in the agent network.
                 False otherwise.
        """
        if agent_spec is None or allow_key is None:
            return False

        empty: Dict[str, Any] = {}

        # Compile a key to look for
        look_for_key: str = allow_key
        if not look_for_key.startswith("allow."):
            look_for_key = f"allow.{allow_key}"

        # Look in the agent spec for the allow key
        allow_extractor = DictionaryExtractor(agent_spec)
        if allow_extractor.get(look_for_key, False):
            return True

        # Any deeper keys? Return early if not.
        if deeper_keys is None or len(deeper_keys) == 0:
            return False

        # Maybe look in the deeper_keys for the allow key
        for deeper_key in deeper_keys:

            # Make the value a list if we don't get one to consolidate on iterative logic
            deeper_list: Union[List[Dict[str, Any]], Dict[str, Any]] = agent_spec.get(deeper_key, empty)
            if not isinstance(deeper_list, list):
                deeper_list = [deeper_list]

            for deeper_spec in deeper_list:
                deeper_extractor = DictionaryExtractor(deeper_spec)
                if deeper_extractor.get(look_for_key, False):
                    return True

        return False
