
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


class InvocationUtil:
    """
    Utility class for handling questions about agent network invocations.
    """

    @staticmethod
    def should_process_as_event(inspector: AgentNetworkInspector, request_dict: Dict[str, Any]) -> bool:
        """
        Check if the agent network should process the request as an event.

        :param inspector: The AgentNetworkInspector instance.  Common internal implementations of
                        AgentNetworkInspector include AgentNetwork, AgentToolRegistry.
        :param request_dict: A ChatRequest dictionary.

        :return: True if the request should be processed as an event, False otherwise.
        """
        if inspector is None:
            return False

        invocation: str = None
        front_man: str = inspector.find_front_man()
        if front_man is not None:
            front_man_spec: Dict[str, Any] = inspector.get_agent_tool_spec(front_man)
            spec_extractor = DictionaryExtractor(front_man_spec)
            # Default invocation id none specified is chatbot
            invocation = spec_extractor.get("function.invocation", "chatbot")

        chat_filter: str = "MINIMAL"
        if request_dict is not None:
            request_extractor = DictionaryExtractor(request_dict)
            chat_filter = request_extractor.get("chat_filter.chat_filter_type", chat_filter)

        # More possibilities will come for more invocations and chat filters.
        if invocation in ("event") and chat_filter in ("MINIMAL"):
            return True

        return False
