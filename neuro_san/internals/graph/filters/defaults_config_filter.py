
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
See class comment for details
"""

from typing import Any
from typing import Dict
from typing import List

from copy import deepcopy

from leaf_common.config.config_filter import ConfigFilter
from leaf_common.config.dictionary_overlay import DictionaryOverlay
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor


class DefaultsConfigFilter(ConfigFilter):
    """
    ConfigFilter implementation for copying top-level defaults
    into individual agents.
    """

    # A mapping of source keys for defaults at the top level to destination
    # keys on the specific tool where the top-level defaults (if any) should be copied.
    DEFAULTS_MAPPING: Dict[str, Dict[str, Any]] = {
        # A value of None implies using a default dictionary where the source key as the same destination
        # key in the tool as well and it applies to all tools.
        "llm_config": None,
        "llm_config.verbose": {
            "dest_key": "verbose",
        },
        "verbose": None,
        "max_steps": None,
        # Deprecated alias. Keep for now to avoid breaking existing networks that use it, but prefer max_steps.
        # It should be removed in the future.
        "max_iterations": None,
        "max_execution_seconds": None,
        "max_attempts": None,
        "error_formatter": None,
        "error_fragments": None,
        "sly_data_schema": {
            "dest_key": "function.sly_data_schema",
            "front_man_only": True,
            "union_fields": ["required"],
        },
    }

    def __init__(self):
        """
        Constructor
        """
        super().__init__()
        self.overlayer = DictionaryOverlay()

    def filter_config(self, basis_config: Dict[str, Any]) \
            -> Dict[str, Any]:
        """
        Filters the given basis config.

        Ideally this would be a Pure Function in that it would not
        modify the caller's arguments so that the caller has a chance
        to decide whether to take any changes returned.

        :param basis_config: The config dictionary to act as the basis
                for filtering
        :return: A config dictionary, potentially modified as per the
                policy encapsulated by the implementation
        """

        if basis_config is None:
            return basis_config

        tools: List[Dict[str, Any]] = basis_config.get("tools")
        if tools is None or len(tools) == 0:
            # Nothing to do. Exit early.
            return basis_config

        # Do a deepcopy of the basis now that we know we are likely to modify it
        result_config: Dict[str, Any] = deepcopy(basis_config)

        # Create a single extractor for the top-level.
        basis_extractor = DictionaryExtractor(result_config)

        # Loop through all the tools making additions.
        tools = result_config.get("tools")

        idx: int = 0
        tool: Dict[str, Any] = None
        for idx, tool in enumerate(tools):
            tool_extractor = DictionaryExtractor(tool)

            # Front-man is the **first** tool in the list (consistent with AgentNetwork.find_front_man()).
            is_front_man: bool = idx == 0

            # Loop through all the keys in the defaults mapping.
            basis_source_key: str = None
            tool_dest_dict: Dict[str, Any] = None
            for basis_source_key, tool_dest_dict in self.DEFAULTS_MAPPING.items():

                basis_value = basis_extractor.get(basis_source_key)
                if basis_value is None:
                    # No value to fill out.
                    continue

                # Account for semantics outlined in default_mapping above
                if tool_dest_dict is None:
                    tool_dest_dict = {
                        "dest_key": basis_source_key,
                        "front_man_only": False,
                        "union_fields": None,
                    }

                tool_dest_key = tool_dest_dict.get("dest_key", basis_source_key)
                tool_front_man_only = tool_dest_dict.get("front_man_only", False)

                if tool_front_man_only and not is_front_man:
                    # Skip this one.
                    continue

                tool_value = tool_extractor.get(tool_dest_key)
                if tool_value is None:
                    # If the tool does not have a value, use the basis_value whole cloth
                    self.set_tool_value(tool, tool_dest_key, deepcopy(basis_value))

                elif isinstance(tool_value, dict) and isinstance(basis_value, dict):
                    # Merge the dictionaries
                    union_fields: List[str] | str | None = tool_dest_dict.get("union_fields")
                    self.merge_dictionaries(tool, tool_dest_key, basis_value, tool_value, union_fields)

                # Otherwise, don't touch the value already in the tool.
                # Don't do anything funny with scalars.
                # Don't try to merge lists (semantics are fragile here).

        return result_config

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def merge_dictionaries(self, tool: Dict[str, Any], tool_dest_key: str,
                           basis_value: Dict[str, Any], tool_value: Dict[str, Any],
                           union_fields: List[str] | str | None = None):
        """
        Merges the basis and tool dictionaries
        :param tool: The tool dictionary itself
        :param tool_dest_key: The destination key in the tool dictionary
        :param basis_value: The dictionary value from the global basis
        :param tool_value: The dictionary value from the tool
        :param union_fields: The fields to union. Currently can not be a multi-part key.
        """

        # overrideable. The values of tool_value are favored.
        self.set_tool_value(tool, tool_dest_key, self.overlayer.overlay(basis_value, tool_value))

        # Take care of special merge cases where lists are unioned
        if union_fields is not None:

            # Case of unioning a single field
            if isinstance(union_fields, str):
                union_fields = [union_fields]

            one_field: str = None
            for one_field in union_fields:

                basis_field: List[str] = basis_value.get(one_field, [])
                tool_field: List[str] = tool_value.get(one_field, [])

                # The merged value is the union of the two sets with no duplicates
                one_field_key: str = f"{tool_dest_key}.{one_field}"
                self.set_tool_value(tool, one_field_key, list(set(basis_field) | set(tool_field)))

    def set_tool_value(self, target: Dict[str, Any], key: str, value: Any):
        """
        Sets the value of a key in the tool dictionary

        :param target: The dictionary to set the value in
        :param key: The key to set the value for. This can be a multi-part key delimited by "."
        :param value: The value to set
        """

        delimiter: str = "."

        # Simple case, there is no field delimiter in the key
        if delimiter not in key:
            target[key] = value
            return

        #
        # Complex case, there is a field delimiter in the key
        #

        # Split the key into parts based on the delimiter
        parts: List[str] = key.split(delimiter)

        # Find the current value of the first part
        first_part: str = parts[0]
        part_value = target.get(first_part)
        if part_value is None:
            # There is no existing value for the first part, so make it a dictionary
            target[first_part] = {}
            part_value = target[first_part]
        elif not isinstance(part_value, dict):
            # Can't descend into non-dict nodes (e.g., tool specs that use a string "function").
            return

        # Reassemble a shorter key for recursion
        remaining_parts: str = ".".join(parts[1:])
        self.set_tool_value(part_value, remaining_parts, value)
