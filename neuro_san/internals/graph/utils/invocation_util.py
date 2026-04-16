
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

from neuro_san.internals.interfaces.invocations import Invocations
from neuro_san.internals.run_context.interfaces.agent_network_inspector import AgentNetworkInspector


class InvocationUtil:
    """
    Utility class for handling questions about agent network invocations.
    """

    @staticmethod
    def get_invocation(inspector: AgentNetworkInspector) -> str:
        """
        Get the invocation type from the agent network.

        :param inspector: The AgentNetworkInspector instance.  Common internal implementations of
                        AgentNetworkInspector include AgentNetwork, AgentToolRegistry.
        :return: A string representing the invocation type.
                 Can be "event" or "chatbot".
        """
        if inspector is None:
            return Invocations.CHATBOT

        invocation: str = None
        front_man: str = None
        try:
            front_man = inspector.find_front_man()
        except ValueError:
            # No front man found.
            pass

        if front_man is not None:
            front_man_spec: Dict[str, Any] = inspector.get_agent_tool_spec(front_man)
            spec_extractor = DictionaryExtractor(front_man_spec)
            # Default invocation if none specified is chatbot
            invocation = spec_extractor.get("function.invocation", Invocations.CHATBOT)

        if isinstance(invocation, dict):
            invocation = invocation.get("invocation_type", Invocations.CHATBOT)

        return invocation

    @staticmethod
    def get_effective_invocation(inspector: AgentNetworkInspector, request_dict: Dict[str, Any]) -> str:
        """
        Check how the agent network should process the request.

        :param inspector: The AgentNetworkInspector instance.  Common internal implementations of
                        AgentNetworkInspector include AgentNetwork, AgentToolRegistry.
        :param request_dict: A ChatRequest dictionary.

        :return: A string representing the invocation type.
                 Can be "event" or "chatbot" for now.
        """
        if inspector is None:
            return Invocations.CHATBOT

        invocation: str = InvocationUtil.get_invocation(inspector)

        chat_filter: str = "MINIMAL"
        if request_dict is not None:
            request_extractor = DictionaryExtractor(request_dict)
            chat_filter = request_extractor.get("chat_filter.chat_filter_type", chat_filter)

        # More possibilities will come for more invocations and chat filters.
        if invocation in (Invocations.EVENT,) and chat_filter in ("MINIMAL",):
            return Invocations.EVENT

        # Note that even if the spec wants event but the request is a MAXIMAL filter,
        # we are taking that to mean that the client wants to hang around for the queued messages
        # to debug what is going on with the event.
        return Invocations.CHATBOT
