
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
sly_data redaction — the CORS-equivalent for the Agent Web protocol.

An agent's spec can declare `allow.to_downstream.sly_data` / `from_downstream`
/ `to_upstream` rules controlling which sly_data keys may cross each
boundary. Values for those rules can take five shapes:

  * False / missing      -> nothing crosses
  * True                 -> everything crosses (debug)
  * List[str]            -> only the listed keys cross, same names
  * Dict[str, bool]      -> per-key true/false
  * Dict[str, str]       -> rename: the value is the destination key name

This is a pure-data filter; it doesn't know about agents, networks, or
async — and so ports cleanly to JS/TS.

Mirror: neuro-san-lite-js/src/redactor.ts
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union


# Possible shapes the allow rule can take.
AllowRule = Union[bool, List[str], Dict[str, Union[bool, str]], None]


def _get_dotted(spec: Dict[str, Any], dotted_key: str) -> Any:
    """Walk a dotted key path into a nested dict, returning None if missing."""
    node: Any = spec
    for part in dotted_key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node


def redact(agent_spec: Optional[Dict[str, Any]],
           sly_data: Optional[Dict[str, Any]],
           config_keys: List[str],
           allow_empty_dict: bool = True) -> Optional[Dict[str, Any]]:
    """
    Filter `sly_data` according to the allow rule found at one of the dotted
    `config_keys` paths within `agent_spec`. Later entries in `config_keys`
    have higher precedence.

    :param agent_spec: The agent spec dict to read the allow rule from.
                       None or missing means "deny all".
    :param sly_data: The sly_data dict to filter.
    :param config_keys: Dotted key paths, e.g. ["allow.to_downstream.sly_data"].
    :param allow_empty_dict: When False, return None instead of {} if nothing
                             is allowed through.

    :return: A NEW dict with only the permitted keys (optionally renamed),
             or None when `allow_empty_dict` is False and the result would be empty.
    """
    if not isinstance(sly_data, dict):
        sly_data = {}

    # Resolve the rule, with later config_keys winning over earlier ones.
    rule: AllowRule = None
    if isinstance(agent_spec, dict):
        for key in config_keys:
            found = _get_dotted(agent_spec, key)
            if found is not None:
                rule = found

    # Empty / missing rule: deny everything (security by default).
    if rule is None or rule is False or rule == {} or rule == []:
        return _maybe_empty({}, allow_empty_dict)

    # Plain True: allow everything through unchanged.
    if rule is True:
        return _maybe_empty(dict(sly_data), allow_empty_dict)

    # List form: turn into dict with True values for canonical processing.
    if isinstance(rule, list):
        rule = {key: True for key in rule if isinstance(key, str)}

    # Dict form: iterate and apply rename / true / false semantics.
    if isinstance(rule, dict):
        out: Dict[str, Any] = {}
        for source_key, dest in rule.items():
            if source_key not in sly_data:
                continue
            value = sly_data[source_key]
            if isinstance(dest, bool):
                if dest:
                    out[source_key] = value
                # else: explicitly denied
            elif isinstance(dest, str) and dest:
                # Rename: copy value to a different key name.
                out[dest] = value
            # Any other value type is treated as denied (defensive).
        return _maybe_empty(out, allow_empty_dict)

    # Unrecognized rule shape: deny everything.
    return _maybe_empty({}, allow_empty_dict)


def _maybe_empty(d: Dict[str, Any], allow_empty: bool) -> Optional[Dict[str, Any]]:
    if not allow_empty and not d:
        return None
    return d
