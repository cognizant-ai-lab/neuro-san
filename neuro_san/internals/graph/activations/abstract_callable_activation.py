
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

from langchain_core.messages.base import BaseMessage

from neuro_san.internals.graph.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.graph.interfaces.callable_activation import CallableActivation
from neuro_san.internals.run_context.interfaces.agent_network_inspector import AgentNetworkInspector
from neuro_san.internals.run_context.interfaces.run_context import RunContext


class AbstractCallableActivation(CallableActivation):
    """
    An abstract implementation of the CallableActivation interface
    containing common policy for all tools.

    Worth noting that this is used as a base implementation for:
        * ClassActivation
        * ExternalActivation
        * CallingActivation
    """

    def __init__(self,
                 factory: AgentToolFactory,
                 agent_tool_spec: Dict[str, Any],
                 sly_data: Dict[str, Any]):
        """
        Constructor

        :param factory: The factory for Agent Tools.
        :param agent_tool_spec: The dictionary describing the JSON agent tool
                            to be used by the instance
        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be an empty dictionary.
        """
        self.factory: AgentToolFactory = factory
        self.agent_tool_spec: Dict[str, Any] = agent_tool_spec
        self.sly_data: Dict[str, Any] = sly_data

        # Subclasses should set up the RunContext for themselves and get the journal from it
        # because not everyone needs an llm_config
        self.run_context: RunContext = None

    def get_agent_tool_spec(self) -> Dict[str, Any]:
        """
        :return: the dictionary describing the data-driven agent
        """
        return self.agent_tool_spec

    def get_name(self) -> str:
        """
        :return: the name of the data-driven agent as it comes from the spec
        """
        agent_spec: Dict[str, Any] = self.get_agent_tool_spec()
        agent_name: str = self.factory.get_name_from_spec(agent_spec)
        return agent_name

    def get_inspector(self) -> AgentNetworkInspector:
        """
        :return: The factory containing all the tool specs
        """
        # For now, our inspector is an AgentToolFactory
        return self.factory

    def get_sly_data(self) -> Dict[str, Any]:
        """
        :return: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be an empty dictionary.
        """
        return self.sly_data

    def get_origin(self) -> List[Dict[str, Any]]:
        """
        :return: A List of origin dictionaries indicating the origin of the run.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
        """
        return self.run_context.get_origin()

    async def delete_resources(self, parent_run_context: RunContext):
        """
        Cleans up after any allocated resources on their server side.
        :param parent_run_context: The RunContext which contains the scope
                    of operation of this CallableActivation
        """
        if self.run_context is not None:
            await self.run_context.delete_resources(parent_run_context)
            self.run_context = None

    async def build(self) -> BaseMessage:
        """
        Main entry point to the class.

        :return: A BaseMessage produced during this process.
        """
        raise NotImplementedError
