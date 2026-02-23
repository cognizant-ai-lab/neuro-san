
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

from neuro_san.internals.run_context.interfaces.agent_spec_provider import AgentSpecProvider
from neuro_san.internals.run_context.interfaces.agent_network_inspector import AgentNetworkInspector
from neuro_san.internals.run_context.interfaces.run import Run


class ToolCaller(AgentSpecProvider):
    """
    Interface for Tools that call Agents/LLMs as functions.
    This is called by langchain Tools and implemented by CallingTool.
    """

    async def make_tool_function_calls(self, component_run: Run) -> Run:
        """
        Calls all of the callable_components' functions

        :param component_run: The Run which the component is operating under
        :return: A potentially updated Run for the component
        """
        raise NotImplementedError

    def get_inspector(self) -> AgentNetworkInspector:
        """
        :return: The AgentNetworkInspector that contains the specs of all the tools
        """
        raise NotImplementedError

    def get_agent_tool_spec(self) -> Dict[str, Any]:
        """
        :return: the dictionary describing the data-driven agent
        """
        raise NotImplementedError

    def get_name(self) -> str:
        """
        :return: the name of the data-driven agent as it comes from the spec
        """
        raise NotImplementedError

    def get_sly_data(self) -> Dict[str, Any]:
        """
        :return: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be an empty dictionary.
        """
        raise NotImplementedError
