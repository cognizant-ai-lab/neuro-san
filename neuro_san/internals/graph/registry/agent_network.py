
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
        self.config: Dict[str, Any] = config
        self.name: str = name
        self.agent_spec_map: Dict[str, Dict[str, Any]] = {}

        # True if this agent network is set to be served as an MCP tool;
        # False otherwise.
        self.is_mcp_network: bool = False

        # The name this network is advertised under when served as an MCP tool:
        # the "name" of its entry in a tools/list response, and the name MCP
        # clients send back in tools/call.
        #
        # It is kept apart from self.name because network names carry the registry
        # sub-directory with a "/" (a network loaded from registries/deep/math_guy.hocon
        # is named "deep/math_guy"), and LLM providers such as OpenAI and Anthropic
        # only accept tool names matching ^[a-zA-Z0-9_-]+$. A "/" in a tool name
        # fails the whole request of any agent that has the tool in its tool list,
        # so nested networks need a different outward-facing spelling. The caller of
        # set_as_mcp_tool() chooses it, normally with McpToolNameFilter().filter():
        #
        #   self.name          mcp_tool_name
        #   "math_guy"         "math_guy"        top-level: nothing to replace, same name
        #   "deep/math_guy"    "deep__math_guy"  nested: "/" becomes "__"
        #   "deep/math_guy"    "calculator"      manifest entry sets "mcp_name": "calculator"
        #
        # The network name stays the internal key everywhere else (network storage,
        # agent authorization, the /api/v1/{agent_name} http path). This field is
        # only the spelling shown to MCP clients; when the two differ, the MCP tool
        # description can still carry self.name in its "title" field so clients can
        # see which network a renamed tool stands for.
        #
        # None until set_as_mcp_tool() is called, i.e. for networks that are not
        # served as MCP tools at all.
        self.mcp_tool_name: str = None

        self.first_agent: str = None

        agent_specs: List[Dict[str, Any]] = self.config.get("tools")
        if agent_specs is not None:
            for agent_spec in agent_specs:
                self.register(agent_spec)

        self.size_in_bytes: int = get_deep_size(self, "bytes")

    def get_config(self) -> Dict[str, Any]:
        """
        :return: The config dictionary passed into the constructor
        """
        return self.config

    def set_as_mcp_tool(self, tool_name: str = None) -> None:
        """
        Marks this agent network as being served as an MCP tool, under the given name.

        Examples, for a network loaded from registries/deep/math_guy.hocon
        (self.name is "deep/math_guy"):

            network.set_as_mcp_tool()
                is_mcp_tool() -> True, get_mcp_tool_name() -> "deep/math_guy"
                (the historical behavior; OpenAI and Anthropic reject the "/")
            network.set_as_mcp_tool(McpToolNameFilter().filter(network.name))
                get_mcp_tool_name() -> "deep__math_guy"
            network.set_as_mcp_tool("calculator")
                get_mcp_tool_name() -> "calculator"   (an explicit manifest "mcp_name")

        For a top-level network (self.name is "math_guy") the first two calls both
        give "math_guy", since there is nothing to replace.

        :param tool_name: The name to advertise the tool under in tools/list and
                          tools/call. Normally this is the provider-safe spelling of
                          the network name from McpToolNameFilter().filter()
                          ("deep/math_guy" gives "deep__math_guy"; a top-level
                          "math_guy" is already safe and stays "math_guy"), or an
                          explicit "mcp_name" from the network's manifest entry.
                          When None or empty (the default) the network name itself is
                          used unchanged, which preserves the historical behavior for
                          callers that do not care about provider-safe names. Note that
                          a nested network advertised that way keeps its "/", which
                          OpenAI and Anthropic reject in tool names.
        """
        self.is_mcp_network = True
        # An empty string is treated like None: an MCP tool must have some name,
        # and the network name is the only sensible fallback.
        if tool_name:
            self.mcp_tool_name = tool_name
        else:
            self.mcp_tool_name = self.name

    def is_mcp_tool(self) -> bool:
        """
        :return: True if this agent network is set to be served as an MCP tool;
                 False otherwise.
        """
        return self.is_mcp_network

    def get_mcp_tool_name(self) -> str:
        """
        Gets the name this network is advertised under as an MCP tool.

        :return: The advertised MCP tool name, or None if it is not served as an MCP tool.
        """
        return self.mcp_tool_name

    def clear_mcp_tool(self) -> None:
        """
        Withdraws this agent network from being served as an MCP tool.

        Used when two networks would otherwise advertise the same tool name and
        one of them has to give way. The network itself stays served over the
        regular (non-MCP) APIs: it remains in network storage, so it can still be
        reached at /api/v1/{name}/... over http and as a same-server "/{name}"
        external agent. It only disappears from MCP tools/list and tools/call.

        Example: registries/a/b.hocon (network "a/b") and registries/a__b.hocon
        (network "a__b") both derive the MCP tool name "a__b". The network whose
        own name already is that tool name keeps it, so the other one is cleared:

            a_slash_b.clear_mcp_tool()
                a_slash_b.is_mcp_tool() -> False, a_slash_b.get_mcp_tool_name() -> None
                tools/list then shows a single "a__b" tool, backed by network "a__b"

        Calling set_as_mcp_tool() again makes the network an MCP tool once more.
        """
        self.is_mcp_network = False
        self.mcp_tool_name = None

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
        front_man: str = None

        # List all agents in the same order as agent network HOCON.
        agent_list: List[str] = list(self.agent_spec_map.keys())

        is_front_man_valid: bool = True
        if len(agent_list) > 0:

            # Front-man is the **first** agent in the agent list
            front_man = agent_list[0]

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
