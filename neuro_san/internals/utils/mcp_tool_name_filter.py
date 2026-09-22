
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
from typing import List

from neuro_san.internals.interfaces.string_filter import StringFilter


class McpToolNameFilter(StringFilter):
    """
    StringFilter that turns a neuro-san network name into a tool name that
    LLM providers will accept.

    Network names come from registry paths and may contain "/" (for example
    "deep/math_guy"). OpenAI and Anthropic both reject tool names outside
    ^[a-zA-Z0-9_-]+$, so a "/" in a tool name fails the whole request.
    filter() maps every "/" to NEURO_SAN_MCP_SEPARATOR ("deep__math_guy")
    and every other character outside ASCII letters, digits, underscore and
    hyphen to UNSAFE_REPLACEMENT ("Agent.1" becomes "Agent_1").

    The mapping is idempotent: a name that is already provider-safe comes
    back unchanged, so applying the filter on both the server and the client
    side is harmless. The MCP server that exposes networks as tools, the
    bundled MCP client session and the LangChain MCP adapter all use this one
    filter (through McpToolNamePolicy) so they agree on the spelling.
    """

    # Separator between registry path segments in neuro-san network names
    # (for example "deep/math_guy"). Registry paths are the source of the "/"
    # that provider tool-name regexes reject.
    NETWORK_SEPARATOR: str = "/"

    # What NETWORK_SEPARATOR becomes in a tool name. This is neuro-san's own
    # convention, hence the name. "__" is used rather than "." because "."
    # fails both the OpenAI and Anthropic regexes, and rather than "-" because
    # a single hyphen is ambiguous with hyphenated stems ("a-b" could be the
    # network "a/b" or a network literally named "a-b"). "__" is also the
    # separator ExternalAgentParsing.get_safe_agent_name uses for "/" (that
    # helper additionally prefixes a leading "__"), so external agents and MCP
    # tools follow the same separator convention.
    NEURO_SAN_MCP_SEPARATOR: str = "__"

    # Substitute for any character outside the provider-safe set that is not
    # a NETWORK_SEPARATOR (for example "." or whitespace). A single "_" keeps
    # such names visibly distinct from the double-underscore path separator.
    UNSAFE_REPLACEMENT: str = "_"

    def filter(self, in_string: str) -> str:
        """
        Converts a neuro-san network name into a provider-safe tool name.

        Every NETWORK_SEPARATOR becomes NEURO_SAN_MCP_SEPARATOR and every
        remaining character outside ASCII letters, digits, underscore and
        hyphen becomes UNSAFE_REPLACEMENT. The mapping is idempotent, so a
        name that has already been converted comes back unchanged.

        :param in_string: The network (or tool) name to convert. None and the
                          empty string are passed through untouched so callers
                          can feed optional values straight in.
        :return: The provider-safe tool name, or the input itself when it is
                 None or empty.
        """
        if in_string is None:
            return None
        if not in_string:
            return ""

        # Map the path separator before the per-character pass so a "/" becomes
        # "__" rather than a lone "_". Doing it the other way round would lose
        # the distinction between a path segment boundary and an unsafe char.
        separated: str = in_string.replace(McpToolNameFilter.NETWORK_SEPARATOR,
                                           McpToolNameFilter.NEURO_SAN_MCP_SEPARATOR)

        safe_chars: List[str] = []
        for char in separated:
            if McpToolNameFilter.is_safe_char(char):
                safe_chars.append(char)
            else:
                safe_chars.append(McpToolNameFilter.UNSAFE_REPLACEMENT)

        return "".join(safe_chars)

    @staticmethod
    def is_safe_char(char: str) -> bool:
        """
        Tells whether a single character is allowed in a provider-safe tool name.

        :param char: A one-character string to test.
        :return: True if the character is an ASCII letter, ASCII digit,
                 underscore or hyphen; False otherwise.
        """
        # str.isalnum() is True for non-ASCII letters and digits (e.g. "é",
        # "²"), which the provider regexes reject, so the ASCII check comes first.
        if not char.isascii():
            return False
        if char.isalnum():
            return True
        return char in (McpToolNameFilter.UNSAFE_REPLACEMENT, "-")
