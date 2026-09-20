
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
import re

from typing import List
from typing import Optional
from typing import Set


class McpToolNamePolicy:
    """
    Single source of truth for turning a neuro-san network name into a
    tool name that LLM providers will accept, and for matching allow-list
    entries against either spelling.

    Network names come from registry paths and may contain "/" (for example
    "deep/math_guy"). OpenAI and Anthropic both reject tool names outside
    ^[a-zA-Z0-9_-]+$, so a "/" in a tool name fails the whole request.
    The MCP server that exposes networks as tools, the bundled MCP client
    session, and the LangChain MCP adapter all need to agree on the rename,
    otherwise a name fixed on one side gets mangled again on the other.
    Putting the rule here keeps them in step and makes the mapping
    idempotent: applying it to an already-safe name changes nothing.

    All methods are static; the class carries no instance state.
    """

    # Separator between registry path segments in neuro-san network names
    # (for example "deep/math_guy"). Registry paths are the source of the "/"
    # that provider tool-name regexes reject.
    NETWORK_SEPARATOR: str = "/"

    # What NETWORK_SEPARATOR becomes in a tool name. "__" is used rather than
    # "." because "." fails both the OpenAI and Anthropic regexes, and rather
    # than "-" because a single hyphen is ambiguous with hyphenated stems
    # ("a-b" could be the network "a/b" or a network literally named "a-b").
    # "__" is also the separator ExternalAgentParsing.get_safe_agent_name uses
    # for "/" (that helper additionally prefixes a leading "__"), so external
    # agents and MCP tools follow the same separator convention.
    SEPARATOR: str = "__"

    # Substitute for any character outside the provider-safe set that is not
    # a NETWORK_SEPARATOR (for example "." or whitespace). A single "_" keeps
    # such names visibly distinct from the double-underscore path separator.
    UNSAFE_REPLACEMENT: str = "_"

    # Strictest tool-name shape common to OpenAI and Anthropic: ASCII letters,
    # digits, underscore and hyphen. The length cap is Anthropic's 128;
    # OpenAI's tighter 64 is handled as a soft limit below.
    TOOL_NAME_PATTERN: str = r"^[a-zA-Z0-9_-]{1,128}$"

    # OpenAI caps tool names at 64 characters. This is warn-only because the
    # same name is still valid for Anthropic and for lenient local providers,
    # so callers log rather than refuse the tool.
    SOFT_MAX_LENGTH: int = 64

    @staticmethod
    def to_tool_name(network_name: str) -> str:
        """
        Converts a neuro-san network name into a provider-safe tool name.

        Every NETWORK_SEPARATOR becomes SEPARATOR and every remaining character
        outside ASCII letters, digits, underscore and hyphen becomes
        UNSAFE_REPLACEMENT. The mapping is idempotent, so a name that has
        already been converted comes back unchanged.

        :param network_name: The network (or tool) name to convert. None and
                             the empty string are passed through untouched so
                             callers can feed optional values straight in.
        :return: The provider-safe tool name, or the input itself when it is
                 None or empty.
        """
        if network_name is None:
            return None
        if not network_name:
            return ""

        # Map the path separator before the per-character pass so a "/" becomes
        # "__" rather than a lone "_". Doing it the other way round would lose
        # the distinction between a path segment boundary and an unsafe char.
        separated: str = network_name.replace(McpToolNamePolicy.NETWORK_SEPARATOR,
                                              McpToolNamePolicy.SEPARATOR)

        safe_chars: List[str] = []
        for char in separated:
            if McpToolNamePolicy.is_safe_char(char):
                safe_chars.append(char)
            else:
                safe_chars.append(McpToolNamePolicy.UNSAFE_REPLACEMENT)

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
        return char in (McpToolNamePolicy.UNSAFE_REPLACEMENT, "-")

    @staticmethod
    def is_valid_tool_name(name: str) -> bool:
        """
        Checks a name against the strictest common provider tool-name pattern.

        :param name: The tool name to validate.
        :return: True if the name fully matches TOOL_NAME_PATTERN;
                 False for None, the empty string, or any non-matching name.
        """
        if not name:
            return False
        return re.fullmatch(McpToolNamePolicy.TOOL_NAME_PATTERN, name) is not None

    @staticmethod
    def is_over_soft_limit(name: str) -> bool:
        """
        Tells whether a tool name exceeds the OpenAI 64-character cap.

        :param name: The tool name to measure.
        :return: True if the name is not None and longer than SOFT_MAX_LENGTH;
                 False otherwise.
        """
        return name is not None and len(name) > McpToolNamePolicy.SOFT_MAX_LENGTH

    @staticmethod
    def matches(entry: str, original_name: str) -> bool:
        """
        Tells whether one allow-list entry refers to the given original tool name,
        accepting either the original spelling or the provider-safe spelling.

        :param entry: A single allow-list entry as written in a hocon file.
        :param original_name: The tool name as advertised by the MCP server.
        :return: True if the entry names the same tool under any accepted
                 spelling; False otherwise.
        """
        # Exact match first: it is the cheap common case and needs no mangling.
        if entry == original_name:
            return True

        # Authors often copy the name the LLM saw in logs or thinking output,
        # which is the already-mangled spelling.
        mangled_original: str = McpToolNamePolicy.to_tool_name(original_name)
        if entry == mangled_original:
            return True

        # Finally compare both sides in mangled form so an entry written with
        # the original spelling still matches a server that has already renamed
        # its tools. The server-side rename applies to_tool_name() to the whole
        # network name, so this has to cover every unsafe character, not only
        # the "/" of nested registry paths: a network "a.b" is advertised as
        # "a_b" and the entry "a.b" must still select it. The mapping is lossy
        # ("a.b" and "a b" both become "a_b"), so an entry could in principle
        # claim an unrelated tool that happens to carry the mangled spelling;
        # resolve() keeps that in check by preferring an exact spelling whenever
        # the server offers one.
        return McpToolNamePolicy.to_tool_name(entry) == mangled_original

    @staticmethod
    def resolve(entry: str, original_names: List[str]) -> Optional[str]:
        """
        Finds the one advertised tool an allow-list entry refers to.

        The exact spelling wins over the provider-safe equivalence. That matters
        when a server offers both "a/b" and "a__b": the entry "a/b" then means
        "a/b" alone and the entry "a__b" means "a__b" alone, so the caller is
        never left choosing between two tools the author did not both ask for.

        :param entry: A single allow-list entry as written in a hocon file.
        :param original_names: The tool names as advertised by the MCP server.
        :return: The advertised name equal to entry when there is one; otherwise
                 the first advertised name that matches() the entry; None when
                 nothing matches or original_names is None or empty.
        """
        # A None original list means the server advertised nothing, so there is
        # nothing to resolve to rather than an error.
        if not original_names:
            return None

        if entry in original_names:
            return entry

        for original_name in original_names:
            if McpToolNamePolicy.matches(entry, original_name):
                return original_name

        return None

    @staticmethod
    def select_allowed(allowed_names: List[str], original_names: List[str]) -> List[str]:
        """
        Picks the advertised tools an allow list permits, resolving each entry
        to exactly one tool with resolve().

        :param allowed_names: The allow-list entries from configuration.
        :param original_names: The tool names as advertised by the MCP server.
        :return: The advertised names some entry resolves to, in the order the
                 server advertised them and without duplicates. Empty when
                 allowed_names is None or empty; callers decide for themselves
                 whether an absent allow list means "allow everything".
        """
        selected: Set[str] = set()
        if allowed_names:
            for entry in allowed_names:
                chosen: Optional[str] = McpToolNamePolicy.resolve(entry, original_names)
                if chosen is not None:
                    selected.add(chosen)

        # Walk the server's list rather than the allow list so the result keeps
        # server order and has no duplicates when two entries (say "a/b" and
        # "a__b" against a server that only offers "a/b") resolve to one tool.
        ordered: List[str] = []
        for original_name in original_names or []:
            if original_name in selected:
                ordered.append(original_name)

        return ordered

    @staticmethod
    def find_unmatched(allowed_names: List[str], original_names: List[str]) -> List[str]:
        """
        Finds allow-list entries that do not correspond to any advertised tool,
        so callers can warn about typos or renamed tools.

        :param allowed_names: The allow-list entries from configuration.
        :param original_names: The tool names as advertised by the MCP server.
        :return: The entries of allowed_names, in their original order, that
                 resolve() to none of original_names. Empty when allowed_names
                 is None or empty.
        """
        unmatched: List[str] = []
        if not allowed_names:
            return unmatched

        for entry in allowed_names:
            if McpToolNamePolicy.resolve(entry, original_names) is None:
                unmatched.append(entry)

        return unmatched
