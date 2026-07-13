
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

from objsize import get_deep_size

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.run_context.interfaces.agent_network_inspector import \
    AgentNetworkInspector


class AgentNetwork(AgentNetworkInspector):
    """
    AgentNetworkInspector implementation for handling queries about a single
    agent network spec.  The data from the hocon file essentially lives here.
    """

    def __init__(self, config: Dict[str, Any], name: str):
        """
        Constructor

        :param config: The dictionary describing the entire agent network
        :param name: The name of the registry
        """
        self.config = config
        self.name = name
        self.agent_spec_map: Dict[str, Dict[str, Any]] = {}

        # True if this agent network is set to be served as an MCP tool;
        # False otherwise.
        self.is_mcp_network: bool = False

        self.first_agent: str = None

        agent_specs = self.config.get("tools")
        if agent_specs is not None:
            for agent_spec in agent_specs:
                self.register(agent_spec)

        self.size_in_bytes: int = get_deep_size(self, "bytes")

    def get_config(self) -> Dict[str, Any]:
        """
        :return: The config dictionary passed into the constructor
        """
        return self.config

    def set_as_mcp_tool(self):
        """
        Marks this agent network as being served as an MCP tool.
        """
        self.is_mcp_network = True

    def is_mcp_tool(self) -> bool:
        """
        :return: True if this agent network is set to be served as an MCP tool;
                 False otherwise.
        """
        return self.is_mcp_network

    def register(self, agent_spec: Dict[str, Any]):
        """
        :param agent_spec: A single agent to register
        """
        if agent_spec is None:
            return

        name: str = self.get_name_from_spec(agent_spec)
        if self.first_agent is None:
            self.first_agent = name

        if name in self.agent_spec_map:
            message: str = f"""
The agent named "{name}" appears to have a duplicate entry in its hocon file for {self.name}.
Agent names must be unique within the scope of a single hocon file.

Some things to try:
1. Rename one of the agents named "{name}". Don't forget to scrutinize all the
   tools references from other agents connecting to it.
2. If one definition is an alternate implementation, consider commenting out
   one of them with "#"-style comments.  (Yes, you can do that in a hocon file).
"""
            raise ValueError(message)

        self.agent_spec_map[name] = agent_spec

    def get_name_from_spec(self, agent_spec: Dict[str, Any]) -> str:
        """
        :param agent_spec: A single agent to register
        :return: The agent name as per the spec
        """
        extractor = DictionaryExtractor(agent_spec)
        name = extractor.get("function.name")
        if name is None:
            name = agent_spec.get("name")

        return name

    def get_agent_tool_spec(self, name: str) -> Dict[str, Any]:
        """
        :param name: The name of the agent tool to get out of the registry
        :return: The dictionary representing the spec registered agent
        """
        # "name" could be in dictionary format with keys like MCP servers.
        if name is None or not isinstance(name, str):
            return None

        return self.agent_spec_map.get(name)

    def find_front_man(self) -> str:
        """
        :return: A single tool name to use as the root of the chat agent.
                 This guy will be user facing. If there are none,
                 an exception will be raised.
        """

        # List all agents in the same order as agent network HOCON.
        agent_list: List[str] = list(self.agent_spec_map.keys())

        is_front_man_valid = True
        if len(agent_list) > 0:

            # Front-man is the **first** agent in the agent list
            front_man: str = agent_list[0]

            # Check the agent spec of the front man for validity
            agent_spec: Dict[str, Any] = self.get_agent_tool_spec(front_man)

            if agent_spec.get("class") is not None:
                # Currently, front man cannot be a coded tool
                is_front_man_valid = False
            elif agent_spec.get("toolbox") is not None:
                # Currently, front man cannot from a toolbox
                is_front_man_valid = False
        else:
            # agent_list is empty! No agent specified
            is_front_man_valid = False

        if is_front_man_valid is False:
            raise ValueError(
                f"""
No valid front man found for the {self.name} agent network.

The front man is the first agent listed under the "tools" section of your agent HOCON file.
However, the front man must not be:
* A CodedTool (i.e., an agent defined with a "class" field)
* A toolbox agent (i.e., defined with a "toolbox" field)
"""
            )

        return front_man

    def get_network_name(self) -> str:
        """
        :return: The network name of this AgentNetwork
        """
        return self.name

    def get_request_timeout_seconds(self) -> float:
        """
        :return: The request timeout in seconds for this AgentNetwork;
                 if not defined, returns 0.0
        """
        extractor = DictionaryExtractor(self.config)
        timeout = extractor.get("request_timeout_seconds")
        if timeout is None:
            return 0.0
        return float(timeout)

    def get_size_in_bytes(self) -> int:
        """
        :return: The size in bytes of this AgentNetwork
        """
        return self.size_in_bytes
