
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
from typing import Union

from urllib.parse import ParseResult
from urllib.parse import urlparse


class ExternalAgentParsing:
    """
    Class handles parsing references to an external agent server
    so that its agents can be used as tools.
    """

    @staticmethod
    def parse_external_agent(agent_url: str) -> Dict[str, str]:
        """
        :param agent_url: The URL describing where to find the desired agent.
        :return: A Dictionary with the following keys:
                "host" - the hostname where the agent lives
                "port" - the port on the host which serves up the agent (if any)
                "agent_name" - the name of the agent on that host

                OR

                None if the parsing of the agent_url was unsuccessful.
        """
        if agent_url is None or len(agent_url) == 0:
            return None

        parse_result: ParseResult = urlparse(agent_url)
        if parse_result is None:
            return None

        if parse_result.path is None or len(parse_result.path) <= 1:
            # We don't have enough characters in the path to even specify
            # an agent that lives on the same server.
            return None

        if not parse_result.path.startswith("/"):
            # This is not an external agent specification
            return None

        host: str = None
        port: str = None
        if len(parse_result.netloc) > 0:
            # We have a host specified
            split: List[str] = parse_result.netloc.split(":")
            host = split[0]
            if len(split) > 1:
                port = split[0]

        # Special case for detecting localhost
        if host is None or len(host) == 0:
            host = "localhost"

        # Get the agent name from the URL by looking at the path
        # Remove any leading slashes from the path for the agent name.
        # Note: While we need to get the agent name for proper gRPC routing,
        #       this is not yet super robust against any non-default case
        #       where some other entity needs a non-standard path for routing
        #       (like a load balancer).  Cross that bridge when we get to it.
        agent_name: str = parse_result.path
        while agent_name.startswith("/"):
            agent_name = agent_name[1:]

        # Assemble the return dictionary
        return_dict = {
            "host": host,
            "port": port,
            "agent_name": agent_name,
        }
        return return_dict

    @staticmethod
    def is_external_agent(agent_url: str) -> bool:
        """
        :param agent_url: The URL describing where to find the desired agent.
        :return: True if the given string is interpretable as an agent url
                (without actually connecting to it).  False otherwise.
        """
        agent_location: Dict[str, str] = ExternalAgentParsing.parse_external_agent(agent_url)
        is_external: bool = agent_location is not None
        return is_external

    @staticmethod
    def is_mcp_tool(tool_ref: Union[str, Dict[str, Any]]) -> bool:
        """
        Check if the tool reference is for an MCP server.
        :param tool_ref: String URL or dict config for MCP tool
        :return: True if this is an MCP tool reference
        """
        # Support both str and dict format;
        # str format: "https://mcp.deepwiki.com/mcp" or "http://localhost:8000/mcp/"
        # dict format:
        # {
        #       "url": "https://mcp.deepwiki.com/mcp",
        #       "tools": ["read_wiki_structure", "ask_question"],
        # }

        # If it is a dict, it is assume it is MCP for now.
        # This may change in the future when Neuro-SAN supports other protocals like A2A.
        if isinstance(tool_ref, dict):
            return True

        if isinstance(tool_ref, str):
            return (tool_ref.startswith("https://mcp") or tool_ref.endswith(("/mcp", "/mcp/")))

        return False

    @staticmethod
    def get_safe_agent_name(agent_url: str) -> str:
        """
        :param agent_url: The URL describing where to find the desired agent.
        :return: A name that is suitable for using within agent toolkits (like langchain)
                for internal tool reference.
        """
        safe_name: str = agent_url
        if ExternalAgentParsing.is_external_agent(agent_url):

            agent_location: Dict[str, str] = ExternalAgentParsing.parse_external_agent(agent_url)

            # FWIW: langchain internal tool references must satisfy the regex: "^[a-zA-Z0-9_-]+$"
            # It's possible that more complex external references might have the agent_name
            # needing futher mangling.  Cross that bridge when we have a real example.
            safe_name = "__" + agent_location.get("agent_name")

        return safe_name
