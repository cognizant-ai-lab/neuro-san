
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
from typing import Iterator
from typing import List
from typing import Set

import re

from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class LintNetworkValidator(AbstractNetworkValidator):
    """
    Best-effort lint-style checks for agent network HOCON files.

    Unlike the other AbstractNetworkValidator subclasses, these are not
    hard correctness checks: they flag things that are usually mistakes
    but can have legitimate explanations the file alone cannot rule out.

    Two checks are provided, each exposed as a public method so callers
    can decide independently which warnings to promote to errors:

    * find_unused_commondefs() — operates on the raw (pre-filter) config
    * find_unresolved_placeholders() — operates on the resolved config
    """

    # Matches commondefs-style replacement tokens: "{word}" where word starts with a letter or
    # underscore. Excludes regex quantifiers like "{3}" or "{3,5}".
    _REPLACEMENT_TOKEN_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

    # Only these top-level agent-spec fields are scanned for leftover placeholders.
    _PLACEHOLDER_FIELDS = ("instructions", "description")

    def __init__(self, raw_config: Dict[str, Any] = None):
        """
        :param raw_config: The pre-commondefs-substitution config dictionary.
                Required for find_unused_commondefs(). May be None if the
                raw config could not be obtained, in which case that check
                is silently skipped.
        """
        self.raw_config: Dict[str, Any] = raw_config

    # --- Static helpers ---

    @staticmethod
    def _iter_strings(value: Any) -> Iterator[str]:
        """
        Yield every string leaf found anywhere within a nested dict/list/scalar.

        :param value: Any nested combination of dict/list/scalar
        :return: An iterator over every string leaf
        """
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            # Recurse into each dict value
            for sub in value.values():
                yield from LintNetworkValidator._iter_strings(sub)
        elif isinstance(value, list):
            # Recurse into each list element
            for sub in value:
                yield from LintNetworkValidator._iter_strings(sub)

    @staticmethod
    def _iter_scalars(value: Any) -> Iterator[Any]:
        """
        Yield every non-dict, non-list leaf found anywhere within a nested structure.

        :param value: Any nested combination of dict/list/scalar
        :return: An iterator over every scalar leaf
        """
        if isinstance(value, dict):
            # Recurse into each dict value
            for sub in value.values():
                yield from LintNetworkValidator._iter_scalars(sub)
        elif isinstance(value, list):
            # Recurse into each list element
            for sub in value:
                yield from LintNetworkValidator._iter_scalars(sub)
        else:
            yield value

    # --- AbstractNetworkValidator interface ---

    def validate(self, candidate: Dict[str, Any]) -> List[str]:
        """
        Run all lint checks, returning every warning in a flat list.

        :param candidate: The fully-resolved agent network config dictionary
        :return: A list of human-readable warning strings
        """
        warnings: List[str] = []
        warnings.extend(self.find_unused_commondefs())
        warnings.extend(self.find_unresolved_placeholders(candidate))
        return warnings

    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        Not used — lint checks operate on the full config, not the
        name-to-spec dict. The validate() override handles dispatch.
        """
        return []

    # --- Individual checks ---

    def find_unused_commondefs(self) -> List[str]:
        """
        Find commondefs.replacement_strings/replacement_values entries that
        are never referenced anywhere else in the network.

        Must be called with the raw (pre-filter) config (passed to __init__)
        so that used entries have not yet been resolved away.

        :return: A list of warning strings, empty if nothing to report
        """
        warnings: List[str] = []
        raw_config: Dict[str, Any] = self.raw_config

        if not isinstance(raw_config, dict):
            return warnings

        commondefs: Any = raw_config.get("commondefs")
        if not isinstance(commondefs, dict) or not commondefs:
            return warnings

        # Commondefs substitution only applies within commondefs (cross-refs) and the tools subtree.
        scan_root: Dict[str, Any] = {
            "tools": raw_config.get("tools", []),
            "commondefs": commondefs,
        }

        # Check replacement_strings: look for {key} tokens in all text
        replacement_strings: Any = commondefs.get("replacement_strings")
        if isinstance(replacement_strings, dict) and replacement_strings:
            haystack: str = "\n".join(self._iter_strings(scan_root))
            # Scan for each defined key as a {key} token
            for key in replacement_strings:
                token: str = "{" + str(key) + "}"
                if token not in haystack:
                    warnings.append(
                        f"""commondefs.replacement_strings.{key} is defined but '{token}' """
                        """never appears anywhere else in the network."""
                    )

        # Check replacement_values: look for bare string matches
        replacement_values: Any = commondefs.get("replacement_values")
        if isinstance(replacement_values, dict) and replacement_values:
            all_scalars: List[Any] = list(self._iter_scalars(scan_root))
            # Scan for each defined key as a bare string value
            for key in replacement_values:
                used: bool = any(
                    scalar == key
                    for scalar in all_scalars
                    if isinstance(scalar, str)
                )
                if not used:
                    warnings.append(
                        f"""commondefs.replacement_values.{key} is defined but the bare string value """
                        f""""{key}" never appears anywhere else in the network."""
                    )

        return warnings

    @staticmethod
    def find_unresolved_placeholders(resolved_config: Dict[str, Any]) -> List[str]:
        """
        Find {word} placeholders that survive commondefs substitution.

        Only scans the 'instructions' and 'description' fields inside the
        tools subtree. Escaped {{...}} forms (used by LangChain prompt
        templates and similar) are skipped.

        :param resolved_config: The fully-resolved agent network config
        :return: A list of warning strings, empty if nothing to report
        """
        warnings: List[str] = []

        if not isinstance(resolved_config, dict):
            return warnings

        tools: Any = resolved_config.get("tools", [])
        if not isinstance(tools, list):
            return warnings

        seen_tokens: Set[str] = set()
        # Scan each tool's instructions and description fields
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            # Only scan the fields that should have commondefs substitutions applied
            for field in LintNetworkValidator._PLACEHOLDER_FIELDS:
                text: Any = tool.get(field)
                if not isinstance(text, str):
                    continue
                # Find all {word}-shaped tokens in this field
                for match in LintNetworkValidator._REPLACEMENT_TOKEN_RE.finditer(text):
                    start: int = match.start()
                    end: int = match.end()
                    # Skip {{word}} — double braces are intentional (LangChain prompt templates, Jinja, etc.)
                    if start > 0 and text[start - 1] == "{":
                        continue
                    if end < len(text) and text[end] == "}":
                        continue
                    token: str = match.group(0)
                    if token in seen_tokens:
                        continue
                    seen_tokens.add(token)
                    warnings.append(
                        f"""Found unresolved placeholder '{token}' in the agent network. """
                        f"""Add a commondefs.replacement_strings.{match.group(1)} entry, """
                        """or remove the placeholder if it was not meant to be a commondef reference."""
                    )

        return warnings
