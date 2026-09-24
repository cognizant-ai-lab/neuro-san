
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

from leaf_common.filters.string_filter import StringFilter

from neuro_san.internals.utils.mcp_tool_name_filter import McpToolNameFilter


class McpToolNamePolicy(StringFilter):
    """
    Single source of truth for how neuro-san names MCP tools: the mapping from
    a network name to a provider-safe tool name, the validation of such names,
    and the matching of allow-list entries written in either spelling.

    The mapping itself is a StringFilter supplied at construction, defaulting
    to McpToolNameFilter, which turns "deep/math_guy" into "deep__math_guy".
    This class is a StringFilter as well and delegates filter() to that
    mapping, so callers that only need the mapping can hold a policy, and
    callers that want a different or composed mapping can inject one. The
    matching methods go through the same filter, so they follow whatever
    mapping was injected.

    The MCP server that exposes networks as tools, the bundled MCP client
    session and the LangChain MCP adapter all use this policy, otherwise a
    name fixed on one side would get mangled again on the other.
    """

    # Strictest tool-name shape common to OpenAI and Anthropic: ASCII letters,
    # digits, underscore and hyphen, at most 128 characters, which is
    # Anthropic's cap.
    TOOL_NAME_PATTERN: str = r"^[a-zA-Z0-9_-]{1,128}$"

    # OpenAI caps tool names at 64 characters, tighter than the 128 of
    # TOOL_NAME_PATTERN. It is a soft limit here: the same name is still valid
    # for Anthropic and for lenient local providers, so callers are expected
    # to warn about a longer name rather than refuse the tool.
    SOFT_MAX_LENGTH: int = 64

    def __init__(self, tool_name_filter: StringFilter = None):
        """
        Constructor

        :param tool_name_filter: The StringFilter that maps a network name to a
                    provider-safe tool name. Defaults to McpToolNameFilter.
        """
        self.tool_name_filter: StringFilter = tool_name_filter
        if self.tool_name_filter is None:
            self.tool_name_filter = McpToolNameFilter()

    def filter(self, in_string: str) -> str:
        """
        Converts a network (or tool) name into its provider-safe spelling,
        using the tool-name filter this policy was constructed with.

        :param in_string: The network or tool name to convert. With the default
                          filter, None and the empty string come back unchanged.
        :return: The provider-safe tool name.
        """
        return self.tool_name_filter.filter(in_string)

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

    def matches(self, entry: str, original_name: str) -> bool:
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
        mangled_original: str = self.filter(original_name)
        if entry == mangled_original:
            return True

        # Finally compare both sides in mangled form so an entry written with
        # the original spelling still matches a server that has already renamed
        # its tools. The server-side rename applies the filter to the whole
        # network name, so this has to cover every unsafe character, not only
        # the "/" of nested registry paths: a network "a.b" is advertised as
        # "a_b" and the entry "a.b" must still select it. The mapping is lossy
        # ("a.b" and "a b" both become "a_b"), so an entry could in principle
        # claim an unrelated tool that happens to carry the mangled spelling;
        # resolve() keeps that in check by preferring an exact spelling whenever
        # the server offers one.
        return self.filter(entry) == mangled_original

    def resolve(self, entry: str, original_names: List[str]) -> Optional[str]:
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
            if self.matches(entry, original_name):
                return original_name

        return None

    def select_allowed(self, allowed_names: List[str], original_names: List[str]) -> List[str]:
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
                chosen: Optional[str] = self.resolve(entry, original_names)
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

    def find_unmatched(self, allowed_names: List[str], original_names: List[str]) -> List[str]:
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
            if self.resolve(entry, original_names) is None:
                unmatched.append(entry)

        return unmatched
