
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

"""
Best-effort lint-style checks for agent network HOCON files.

Unlike neuro_san.internals.validation.network.*, these are not hard
correctness checks run by the server at load time: they flag things that
are usually mistakes (a stale commondef, a typo in a replacement token, an
allow.*.sly_data entry that doesn't line up with any declared schema) but
can have legitimate explanations the file alone can't rule out. Callers
should treat their output as warnings, not errors, unless a user opts in
to stricter behavior (see hocon_validator_cli's --strict flag).
"""

from typing import Any
from typing import Dict
from typing import Iterator
from typing import List
from typing import Set

import re

# Matches the "{word}" token form used by commondefs.replacement_strings,
# e.g. "Perform the {operation} operation." -> token "{operation}".
# Requires a letter/underscore first character so this doesn't also match
# a regex quantifier like "{3}" or "{3,5}" sitting in an unrelated string.
_REPLACEMENT_TOKEN_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# The four places in an "allow" dictionary that carry a nested "sly_data" policy.
# (allow.connectivity and any other custom keys a CodedTool might stash under
# "allow" are intentionally not touched here.)
_ALLOW_SLY_DATA_SECTIONS = ("to_downstream", "from_downstream", "to_upstream", "to_tracing")


def _iter_strings(value: Any) -> Iterator[str]:
    """
    :param value: Any nested combination of dict/list/scalar
    :return: An iterator over every string leaf found anywhere within value
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for sub_value in value.values():
            yield from _iter_strings(sub_value)
    elif isinstance(value, list):
        for sub_value in value:
            yield from _iter_strings(sub_value)


def _iter_scalars(value: Any) -> Iterator[Any]:
    """
    :param value: Any nested combination of dict/list/scalar
    :return: An iterator over every non-dict, non-list leaf value found anywhere within value
    """
    if isinstance(value, dict):
        for sub_value in value.values():
            yield from _iter_scalars(sub_value)
    elif isinstance(value, list):
        for sub_value in value:
            yield from _iter_scalars(sub_value)
    else:
        yield value


def find_unused_commondefs(raw_config: Dict[str, Any]) -> List[str]:
    """
    Find commondefs.replacement_strings/replacement_values entries that are
    never referenced anywhere else in the network.

    Must be called with the *raw*, pre-filter config (e.g. from
    RawAgentNetworkRestorer): once the standard commondefs filter chain has
    run, a used definition has already been swapped in at its use site and
    an unused one has simply vanished, so there is nothing left to look for.

    :param raw_config: The unresolved agent network config dictionary, exactly
            as read from the HOCON/JSON source (includes already resolved).
    :return: A list of human-readable warning strings. Empty if there is
            nothing to report, or if the file has no commondefs section.
    """
    warnings: List[str] = []

    if not isinstance(raw_config, dict):
        return warnings

    commondefs: Any = raw_config.get("commondefs")
    if not isinstance(commondefs, dict) or not commondefs:
        return warnings

    # commondefs substitution is only ever applied to the commondefs dictionary
    # itself (entries can reference each other) and to the "tools" subtree.
    # See NetworkConfigFilterChain / AbstractCommonDefsConfigFilter.filter_config.
    scan_root: Dict[str, Any] = {
        "tools": raw_config.get("tools", []),
        "commondefs": commondefs,
    }

    replacement_strings: Any = commondefs.get("replacement_strings")
    if isinstance(replacement_strings, dict) and replacement_strings:
        haystack: str = "\n".join(_iter_strings(scan_root))
        for key in replacement_strings:
            token: str = "{" + str(key) + "}"
            if token not in haystack:
                warnings.append(
                    f"commondefs.replacement_strings.{key} is defined but '{token}' "
                    "never appears anywhere else in the network."
                )

    replacement_values: Any = commondefs.get("replacement_values")
    if isinstance(replacement_values, dict) and replacement_values:
        all_scalars: List[Any] = list(_iter_scalars(scan_root))
        for key in replacement_values:
            used: bool = any(scalar == key for scalar in all_scalars if isinstance(scalar, str))
            if not used:
                warnings.append(
                    f'commondefs.replacement_values.{key} is defined but the bare string '
                    f'value "{key}" never appears anywhere else in the network.'
                )

    return warnings


def find_unresolved_replacement_strings(resolved_config: Dict[str, Any]) -> List[str]:
    """
    Find "{word}" placeholders that survive commondefs substitution.

    Must be called with the fully-resolved config (after the standard
    commondefs/defaults/name-correction filter chain has run, e.g. the
    config a HoconValidatorCli normally validates). A leftover "{word}"
    token at that point means no commondefs.replacement_strings.word entry
    matched it, which almost always indicates a typo in the token or a
    missing commondefs entry.

    :param resolved_config: The fully-resolved agent network config dictionary.
    :return: A list of human-readable warning strings, one per distinct
            unresolved token found. Empty if there is nothing to report.
    """
    warnings: List[str] = []

    if not isinstance(resolved_config, dict):
        return warnings

    # String substitution is only ever applied within the "tools" subtree
    # (see NetworkConfigFilterChain). Scanning the whole config would also
    # catch the original, intentionally-unsubstituted commondefs.replacement_strings
    # definitions themselves, which are not bugs.
    tools: Any = resolved_config.get("tools", [])

    seen_tokens: Set[str] = set()
    for text in _iter_strings(tools):
        for match in _REPLACEMENT_TOKEN_PATTERN.finditer(text):
            token: str = match.group(0)
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            warnings.append(
                f"Found unresolved placeholder '{token}' in the agent network. "
                f"Add a commondefs.replacement_strings.{match.group(1)} entry, "
                "or remove the placeholder if it was not meant to be a commondef reference."
            )

    return warnings


def _add_schema_property_keys(schema: Any, declared: Set[str]):
    """
    :param schema: A sly_data_schema/sly_data_output_schema-shaped dictionary, or None
    :param declared: The set to add any top-level property keys to, in place
    """
    if not isinstance(schema, dict):
        return
    properties: Any = schema.get("properties")
    if isinstance(properties, dict):
        declared.update(properties.keys())


def _collect_declared_sly_data_keys(resolved_config: Dict[str, Any]) -> Set[str]:
    """
    :param resolved_config: The fully-resolved agent network config dictionary
    :return: The set of sly_data keys declared anywhere in the network's
            sly_data_schema/sly_data_output_schema properties (top-level or
            per-agent).
    """
    declared: Set[str] = set()

    _add_schema_property_keys(resolved_config.get("sly_data_schema"), declared)

    tools: Any = resolved_config.get("tools", [])
    if not isinstance(tools, list):
        return declared

    for tool in tools:
        if not isinstance(tool, dict):
            continue

        function: Any = tool.get("function")
        if isinstance(function, dict):
            _add_schema_property_keys(function.get("sly_data_schema"), declared)
            _add_schema_property_keys(function.get("sly_data_output_schema"), declared)

        # Some specs place these directly on the agent spec rather than under "function".
        _add_schema_property_keys(tool.get("sly_data_schema"), declared)
        _add_schema_property_keys(tool.get("sly_data_output_schema"), declared)

    return declared


def _sly_data_keys_from_allow_value(value: Any) -> List[str]:
    """
    :param value: The value of an allow.<section>.sly_data entry: either a
            dict (key -> bool/str translation) or a list of key strings.
    :return: The sly_data keys being referenced (dict keys, or list entries).
            Translation target strings (the new name a key is renamed to)
            are not included: it is the original key that must exist.
    """
    if isinstance(value, dict):
        return [key for key in value if isinstance(key, str)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def find_unset_allow_sly_data_keys(resolved_config: Dict[str, Any]) -> List[str]:
    """
    Find allow.<to_downstream|from_downstream|to_upstream|to_tracing>.sly_data
    keys that are not declared in any sly_data_schema/sly_data_output_schema
    anywhere in the network.

    This is a best-effort static check: sly_data keys are often set
    programmatically by a CodedTool with no corresponding schema entry
    anywhere in the hocon file, which this check cannot see. Treat a hit as
    "double check this key is actually populated somewhere", not proof of
    a bug.

    :param resolved_config: The fully-resolved agent network config dictionary.
    :return: A list of human-readable warning strings. Empty if there is
            nothing to report.
    """
    warnings: List[str] = []

    if not isinstance(resolved_config, dict):
        return warnings

    declared: Set[str] = _collect_declared_sly_data_keys(resolved_config)

    def check_allow_block(allow: Any, context: str):
        if not isinstance(allow, dict):
            return
        for section in _ALLOW_SLY_DATA_SECTIONS:
            section_value: Any = allow.get(section)
            if not isinstance(section_value, dict):
                continue
            sly_data_value: Any = section_value.get("sly_data")
            for key in _sly_data_keys_from_allow_value(sly_data_value):
                if key not in declared:
                    warnings.append(
                        f"{context}: allow.{section}.sly_data references key '{key}', which is "
                        "not declared in any sly_data_schema/sly_data_output_schema in this "
                        "file. This may be a false positive if the key is set by a CodedTool at "
                        "runtime, or declared by an external agent network (one referenced via "
                        "'/...') that this check cannot see; otherwise it may be a typo or a "
                        "stale entry."
                    )

    check_allow_block(resolved_config.get("allow"), "<network>")

    tools: Any = resolved_config.get("tools", [])
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict):
                check_allow_block(tool.get("allow"), tool.get("name", "<unnamed>"))

    return warnings
