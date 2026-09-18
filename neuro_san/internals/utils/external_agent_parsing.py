
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
from typing import Optional
from typing import Union

from urllib.parse import ParseResult
from urllib.parse import urlparse

from neuro_san.interfaces.agent_session_constants import AgentSessionConstants


class ExternalAgentParsing:
    """
    Class handles parsing references to an external agent server
    so that its agents can be used as tools.
    """

    @staticmethod
    def parse_external_agent(agent_url: str, server_port: int = None) -> Dict[str, str]:
        """
        Parses an external agent reference into the host, port, agent name and scheme it points at.

        :param agent_url: The URL describing where to find the desired agent.
        :param server_port: The port that the server is listening on
                            Does not have to be set for all operations.
        :return: A Dictionary with the following keys:
                "host" - the hostname where the agent lives; an IPv6 literal
                         keeps its square brackets so it can be placed in a URL
                "port" - the port on the host which serves up the agent (if any)
                "agent_name" - the name of the agent on that host
                "scheme" - the url scheme of the reference ("http" or
                           "https"), or "" when the reference has no
                           scheme, e.g. "/math_guy" for an agent on the
                           same server.

                OR

                None if the parsing of the agent_url was unsuccessful.
        """
        if agent_url is None or len(agent_url) == 0:
            return None

        port_number: Optional[int] = None
        try:
            parse_result: ParseResult = urlparse(agent_url)
            # .port raises ValueError for a non-numeric or out-of-range port,
            # which is as unparseable as a malformed netloc.
            port_number = parse_result.port
        except ValueError:
            # e.g. mismatched brackets parsed as an invalid IPv6 netloc.
            # Unparseable means "not an external agent", per this method's
            # contract of returning None on unsuccessful parsing.
            return None
        if parse_result is None:
            return None

        if parse_result.path is None or len(parse_result.path) <= 1:
            # We don't have enough characters in the path to even specify
            # an agent that lives on the same server.
            return None

        # An authority that is present but carries no host ("http://user@/agent",
        # "http://:8080/agent") is malformed. It must not fall through to the
        # localhost default below, which would silently turn a broken remote
        # reference into a call to a local agent of the same name. An explicit
        # but empty port ("https://host:/agent") is malformed too: .port reports
        # it as None, so without this check it would receive a default port.
        # The host-info part is what follows any userinfo "@".
        hostinfo: str = parse_result.netloc.rsplit("@", 1)[-1]
        malformed_authority: bool = bool(parse_result.netloc) and \
            (not parse_result.hostname or hostinfo.endswith(":"))
        if not parse_result.path.startswith("/") or malformed_authority:
            # Either not an external agent specification, or unparseable.
            return None

        # No normalization is done on the scheme: the network validators
        # (AbstractNetworkValidator.is_url_or_path) only recognize the lower-case
        # "http://" and "https://" spellings in hocon tool references, so that is
        # the only form that reaches this parser in normal operation.
        scheme: str = parse_result.scheme or ""

        host: str = None
        port: str = None
        if parse_result.hostname:
            # hostname/port are bracket-aware, unlike a naive netloc.split(":"),
            # which turned "[2001:db8::1]" into host "[2001" and port "db8".
            # hostname also drops any userinfo and lower-cases the name.
            host = parse_result.hostname
            if ":" in host:
                # hostname strips the brackets from an IPv6 literal; put them
                # back so the session layer can build "https://[v6]:443/...".
                host = f"[{host}]"
            if port_number is not None:
                # .port only validated the number. Return the port as written in
                # the reference ("0443" stays "0443"), as this parser always has.
                # When present, the port is what follows the last ":" of the
                # netloc, which is bracket-safe because an IPv6 literal ends in "]".
                port = parse_result.netloc.rsplit(":", 1)[1]

        # Special case for detecting localhost
        if host is None or len(host) == 0:
            host = "localhost"

        if host == "localhost" and port is None:
            # If we are localhost and no port was specified in the url,
            # use the port that was configured for the server.
            # If this is not set, it will default to None, which is fine.
            port = server_port

        if port is None and scheme == "https":
            # An https reference without an explicit port is expected to reach
            # a TLS-terminating proxy on the well-known https port, not the bare
            # 8080 dev server the session layer defaults to. Only https gets this
            # treatment: http and scheme-less references keep port None so the
            # session layer's own http default still applies. This runs after
            # the localhost rule so a configured server_port wins for localhost.
            port = str(AgentSessionConstants.DEFAULT_HTTPS_PORT)

        # Get the agent name from the URL by looking at the path.
        # Remove any leading slashes from the path for the agent name.
        # Note: The agent name becomes the {agent_name} segment of the
        #       /api/v1/{agent_name}/{method} http path and the key for the
        #       Direct-session registry lookup on the same server, so it may
        #       itself contain "/" for nested registries. This is not yet
        #       robust against any non-default case where some other entity
        #       needs a non-standard path for routing (like a load balancer).
        #       Cross that bridge when we get to it.
        agent_name: str = parse_result.path
        while agent_name.startswith("/"):
            agent_name = agent_name[1:]

        # Assemble the return dictionary
        return_dict = {
            "host": host,
            "port": port,
            "agent_name": agent_name,
            "scheme": scheme,
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
        # str format: a canonical MCP server URI, e.g. "https://mcp.deepwiki.com/mcp",
        #             "http://localhost:8000/mcp/", or "https://deepwiki.com/mcp/free"
        # dict format:
        # {
        #       "url": "https://mcp.deepwiki.com/mcp",
        #       "tools": ["read_wiki_structure", "ask_question"],
        # }

        # If it is a dict, it is assumed it is MCP for now.
        # This may change in the future when Neuro SAN supports other protocals like A2A.
        if isinstance(tool_ref, dict):
            return True

        if not isinstance(tool_ref, str):
            return False

        # Validate against the MCP canonical server URI rules:
        # https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization#canonical-server-uri
        # - MUST have an http/https scheme (accepted case-insensitively for robustness)
        # - MUST have a host
        # - MUST NOT contain a fragment
        parsed: ParseResult = None
        try:
            parsed = urlparse(tool_ref)
        except ValueError:
            return False

        if parsed.scheme.lower() not in ("http", "https"):
            return False
        if not parsed.netloc or parsed.fragment:
            return False

        # Heuristic to distinguish an MCP server URI from a Neuro SAN external agent URL:
        # require "mcp" to appear either as a label in the hostname (e.g. "mcp.example.com")
        # or as any path segment (e.g. "/mcp", "/mcp/free", "/server/mcp").
        host_labels = (parsed.hostname or "").lower().split(".")
        path_segments: List[str] = []
        for seg in parsed.path.split("/"):
            if seg:
                path_segments.append(seg.lower())
        return "mcp" in host_labels or "mcp" in path_segments

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
            # needing further mangling.  Cross that bridge when we have a real example.
            # As a part of valid URL, agent_name can only have "/" in it.
            safe_name = "__" + agent_location.get("agent_name").replace("/", "__")

        return safe_name
