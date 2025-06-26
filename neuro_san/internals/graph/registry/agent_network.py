
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT
from typing import Any
from typing import Dict
from typing import List

from copy import copy

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.run_context.interfaces.agent_network_inspector import AgentNetworkInspector


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

        self.first_agent: str = None

        agent_specs = self.config.get("tools")
        if agent_specs is not None:
            for agent_spec in agent_specs:
                self.register(agent_spec)

    def get_config(self) -> Dict[str, Any]:
        """
        :return: The config dictionary passed into the constructor
        """
        return self.config

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
The agent named "{name}" appears to have a duplicate entry in its hocon file.
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
        if name is None:
            return None

        return self.agent_spec_map.get(name)

    def find_front_man(self) -> str:
        """
        :return: A single tool name to use as the root of the chat agent.
                 This guy will be user facing.  If there are none or > 1,
                 an exception will be raised.
        """
        front_men: List[str] = []

        # Identify the "front-man" agent.
        # Primary heuristic: an agent with defined instructions and a function that takes no parameters.
        # The presence of instructions ensures it was explicitly defined, since users may add parameters
        # to front-men, making function signature alone unreliable.
        for name, agent_spec in self.agent_spec_map.items():
            instructions: str = agent_spec.get("instructions")
            function: Dict[str, Any] = agent_spec.get("function")
            if instructions is not None and function is not None and function.get("parameters") is None:
                front_men.append(name)

        if len(front_men) == 0:
            # The best way to find a front man is to see which agent was registered first
            front_men.append(self.first_agent)

        # Check for validity of our front-man candidates.
        valid_front_men: List[str] = copy(front_men)
        for front_man in front_men:

            # Check the agent spec of the front man for validity
            agent_spec: Dict[str, Any] = self.get_agent_tool_spec(front_man)

            if agent_spec.get("class") is not None:
                # Currently, front man cannot be a coded tool
                valid_front_men.remove(front_man)
            elif agent_spec.get("toolbox") is not None:
                # Currently, front man cannot from a toolbox
                valid_front_men.remove(front_man)

        if len(valid_front_men) == 0:
            raise ValueError("""
No front man found.
Here are some pre-conditions for an agent in your network to be a potential front man:
1) The agent's "function" does not have any "parameters" defined OR
2) The agent is the first listed among the "tools" of your agent hocon file

Disqualifiers. A front man cannot:
* be a CodedTool with a "class" definition
* be a tool with a "toolbox" definition
""")

        if len(valid_front_men) > 1:
            raise ValueError(f"Found > 1 front man for chat. Possibilities: {valid_front_men}")

        front_man: str = valid_front_men[0]

        return front_man

    def get_network_name(self) -> str:
        """
        :return: The network name of this AgentNetwork
        """
        return self.name
