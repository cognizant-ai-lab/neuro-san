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
from typing import Set


class SlyDataLlmConfigUtil:
    """
    Static utility class for handling the llm_config portion of a client's sly_data,
    which carries per-request llm settings such as API keys for user billing.
    """

    @staticmethod
    def replace_llm_config_with_sly_data(
                config: Dict[str, Any],
                sly_data: Dict[str, Any],
                llm_config_schema: Dict[str, Any] = None
            ) -> Dict[str, Any] | Set[str]:
        """
        Get any required api keys into the config.
        :param config: The fully specified llm config which is a product of
                    DefaultLlmFactory.create_full_llm_config().
        :param sly_data: A user-provided dictionary of private data,
                from which we might extract API keys to use for user billing.
                Can be None indicating no API keys are provided at all and the system defaults will be used.
        :param llm_config_schema: The llm_config portion of the agent network front man's sly_data_schema,
                describing the sly_data.llm_config keys clients are expected to send. Can be None.
                A missing key that this schema declares as optional is set to None instead of being reported.
                A missing key whose "anyOf" or "oneOf" list another provided alternative satisfies
                is not reported either, but the config cannot be used.
        :return: The config with any required api keys replaced, or a set of missing
            required config field names if any required api keys were not provided.
            The set is empty when the only missing keys are alternatives the client satisfied otherwise,
            so the caller skips this config without reporting anything about it.
        """
        optional_set: Set[str] = SlyDataLlmConfigUtil.get_optional_keys(llm_config_schema)

        use_api_keys: Dict[str, str] = {}
        if sly_data is not None and isinstance(sly_data, dict):
            use_api_keys = sly_data.get("llm_config", use_api_keys)

        excused_set: Set[str] = SlyDataLlmConfigUtil.get_excused_keys(llm_config_schema, use_api_keys)
        has_excused: bool = False

        # Loop through each of the config values and replace any "sly_data" values
        # with their corresponding values from the llm_config dictionary.
        required_set: Set[str] = set()
        key: str = None
        value: Any = None
        for key, value in config.items():
            # If any value is "sly_data", replace it with the same value from the llm_config dictionary
            small_value: str = str(value).lower()
            if small_value == "sly_data":
                # If we have a value in the sly_data.llm_config dictionary, use it,
                new_value: Any = SlyDataLlmConfigUtil.get_provided_value(use_api_keys, key)
                if new_value is not None:
                    config[key] = new_value
                elif key in optional_set:
                    # Let the llm policy fall back to its environment variable or default.
                    config[key] = None
                elif key in excused_set:
                    # Not setting this to None, as the llm policy would then fall back to
                    # the server's own api key and bill the server instead of the client.
                    has_excused = True
                else:
                    # Add to the list of complaints about what is missing.
                    required_set.add(key)

        if len(required_set) > 0:
            # We have complaints about what is missing. Return that.
            return required_set

        if has_excused:
            # The client satisfied the schema with other keys, so skip this config without complaint.
            return required_set

        # We have a nice complete config. Return that.
        return config

    @staticmethod
    def get_excused_keys(llm_config_schema: Dict[str, Any], provided: Dict[str, Any]) -> Set[str]:
        """
        Get the keys that the client no longer needs to send because it fully provided another
        alternative of the same "anyOf" or "oneOf" list.

        :param llm_config_schema: The llm_config portion of the agent network front man's sly_data_schema.
                Can be None.
        :param provided: The sly_data.llm_config dictionary the client sent.
        :return: The set of keys from every alternative of each satisfied group, less any key
                the schema always requires. This is empty when there is no usable schema.
        """
        excused_set: Set[str] = set()
        if not isinstance(llm_config_schema, dict) or not isinstance(provided, dict):
            return excused_set

        groups: List[List[List[str]]] = []
        SlyDataLlmConfigUtil.collect_alternative_groups(llm_config_schema, groups)

        # Loop through each group to see whether the client satisfied any of its alternatives.
        group: List[List[str]] = None
        for group in groups:
            satisfied: bool = False
            # Loop through each alternative of the group.
            branch: List[str] = None
            for branch in group:
                if SlyDataLlmConfigUtil.is_branch_provided(branch, provided):
                    satisfied = True
                    break
            if not satisfied:
                continue

            # Loop through each alternative again to excuse all of its keys.
            for branch in group:
                excused_set.update(branch)

        always_set: Set[str] = set()
        SlyDataLlmConfigUtil.collect_always_required_keys(llm_config_schema, always_set)
        excused_set.difference_update(always_set)
        return excused_set

    @staticmethod
    def is_branch_provided(branch: List[str], provided: Dict[str, Any]) -> bool:
        """
        Tell whether the client sent a value for every key that an alternative requires.

        :param branch: The required keys of one "anyOf" or "oneOf" alternative.
        :param provided: The sly_data.llm_config dictionary the client sent.
        :return: True if every key of the alternative has a value, False otherwise.
        """
        # Loop through each key the alternative requires.
        key: str = None
        for key in branch:
            if SlyDataLlmConfigUtil.get_provided_value(provided, key) is None:
                return False
        return True

    @staticmethod
    def get_provided_value(provided: Dict[str, Any], key: str) -> Any:
        """
        Get the value the client sent for a key, treating a blank string as not set.

        :param provided: The sly_data.llm_config dictionary the client sent.
        :param key: The key to look up.
        :return: The value with any string stripped of leading and trailing whitespace,
                or None if the key is absent, None, or a string that is empty after stripping.
        """
        value: Any = provided.get(key)
        if isinstance(value, str):
            # Remove leading and trailing whitespace because often these values
            # are going into http headers which don't like the extra whitespace.
            value = value.strip()
            if len(value) == 0:
                return None
        return value

    @staticmethod
    def get_optional_keys(llm_config_schema: Dict[str, Any]) -> Set[str]:
        """
        Get the keys that the llm_config schema declares but never requires.
        A key named in any "required" list, including those inside "anyOf", "oneOf" or "allOf"
        branches, can be required and so is not optional.

        :param llm_config_schema: The llm_config portion of the agent network front man's sly_data_schema.
                Can be None.
        :return: The set of keys in the schema's properties that no "required" list names.
                This is empty when there is no usable schema.
        """
        optional_set: Set[str] = set()
        if not isinstance(llm_config_schema, dict):
            return optional_set

        properties: Dict[str, Any] = llm_config_schema.get("properties")
        if not isinstance(properties, dict):
            return optional_set

        required_set: Set[str] = set()
        SlyDataLlmConfigUtil.collect_required_keys(llm_config_schema, required_set)

        # Loop through each declared property to keep the ones that are never required.
        key: str = None
        for key in properties.keys():
            if key not in required_set:
                optional_set.add(key)

        return optional_set

    @staticmethod
    def collect_required_keys(schema: Dict[str, Any], required_set: Set[str]) -> None:
        """
        Add every key named in a "required" list of the schema, and of its
        "anyOf", "oneOf" and "allOf" branches, to the given set.

        :param schema: A JSON schema dictionary for an object.
        :param required_set: The set to which the required keys are added.
        """
        required: List[str] = schema.get("required")
        if isinstance(required, list):
            required_set.update(required)

        # Loop through each combinator, as any of its branches can make a key required.
        combinator: str = None
        for combinator in ("anyOf", "oneOf", "allOf"):
            branches: List[Dict[str, Any]] = schema.get(combinator)
            if not isinstance(branches, list):
                continue

            # Loop through each branch schema of the combinator.
            branch: Dict[str, Any] = None
            for branch in branches:
                if isinstance(branch, dict):
                    SlyDataLlmConfigUtil.collect_required_keys(branch, required_set)

    @staticmethod
    def describe_missing_keys(missing_keys: List[str], llm_config_schema: Dict[str, Any] = None) -> str:
        """
        Describe the sly_data.llm_config keys a client needs to send when no LLM could be created.
        Keys the schema always requires and the alternatives of its "anyOf" and "oneOf" lists
        are described as such. Without schema information, every key is listed as an alternative.

        :param missing_keys: The keys reported missing by replace_llm_config_with_sly_data()
                across all of the fallbacks that were tried.
        :param llm_config_schema: The llm_config portion of the agent network front man's sly_data_schema.
                Can be None.
        :return: A multi-line message for the client.
        """
        missing_set: Set[str] = set(missing_keys)

        always_set: Set[str] = set()
        groups: List[List[List[str]]] = []
        if isinstance(llm_config_schema, dict):
            SlyDataLlmConfigUtil.collect_always_required_keys(llm_config_schema, always_set)
            SlyDataLlmConfigUtil.collect_alternative_groups(llm_config_schema, groups)
        always_set.intersection_update(missing_set)

        # Only describe the alternatives that a missing key could fulfill.
        group_lines: List[str] = []
        described_set: Set[str] = set(always_set)
        group: List[List[str]] = None
        for group in groups:
            branch_texts: List[str] = []
            # Loop through each alternative of the group.
            branch: List[str] = None
            for branch in group:
                branch_missing: List[str] = []
                # Loop through each key the alternative requires.
                key: str = None
                for key in sorted(branch):
                    if key in missing_set:
                        branch_missing.append(key)
                if len(branch_missing) > 0:
                    branch_texts.append(" and ".join(branch_missing))
                    described_set.update(branch_missing)
            if len(branch_texts) > 0:
                group_lines.append(f"    one of: {', '.join(branch_texts)}\n")

        undescribed: List[str] = sorted(missing_set - described_set)

        message: str = None
        if len(always_set) == 0 and len(group_lines) == 0:
            # No schema information applies, so the keys are alternatives across the fallbacks.
            message = "LLM operation for this agent requires at least one of the following set in " \
                "sly_data.llm_config:\n"
            # Loop through each missing key to list it on its own line.
            missing_key: str = None
            for missing_key in undescribed:
                message += f"    {missing_key}\n"
            return message

        message = "LLM operation for this agent requires the following set in sly_data.llm_config:\n"
        if len(always_set) > 0:
            message += f"    all of: {', '.join(sorted(always_set))}\n"
        message += "".join(group_lines)
        if len(undescribed) > 0:
            message += f"    one of (not in the sly_data_schema): {', '.join(undescribed)}\n"
        return message

    @staticmethod
    def collect_always_required_keys(schema: Dict[str, Any], always_set: Set[str]) -> None:
        """
        Add every key that the schema requires unconditionally, from its own "required" list
        and those of its "allOf" branches, to the given set.

        :param schema: A JSON schema dictionary for an object.
        :param always_set: The set to which the always-required keys are added.
        """
        required: List[str] = schema.get("required")
        if isinstance(required, list):
            always_set.update(required)

        branches: List[Dict[str, Any]] = schema.get("allOf")
        if not isinstance(branches, list):
            return

        # Loop through each allOf branch, as every one of them applies.
        branch: Dict[str, Any] = None
        for branch in branches:
            if isinstance(branch, dict):
                SlyDataLlmConfigUtil.collect_always_required_keys(branch, always_set)

    @staticmethod
    def collect_alternative_groups(schema: Dict[str, Any], groups: List[List[List[str]]]) -> None:
        """
        Add the "required" lists of the schema's "anyOf" and "oneOf" branches, and of those
        inside its "allOf" branches, to the given list of groups.

        :param schema: A JSON schema dictionary for an object.
        :param groups: The list to which each combinator's alternatives are added,
                as one list of required-key lists per combinator.
        """
        # Loop through each combinator whose branches are alternatives.
        combinator: str = None
        for combinator in ("anyOf", "oneOf"):
            branches: List[Dict[str, Any]] = schema.get(combinator)
            if not isinstance(branches, list):
                continue

            group: List[List[str]] = []
            # Loop through each alternative to get its required keys.
            branch: Dict[str, Any] = None
            for branch in branches:
                if not isinstance(branch, dict):
                    continue
                required: List[str] = branch.get("required")
                if isinstance(required, list) and len(required) > 0:
                    group.append(required)
            if len(group) > 0:
                groups.append(group)

        all_of: List[Dict[str, Any]] = schema.get("allOf")
        if not isinstance(all_of, list):
            return

        # Loop through each allOf branch, as each can hold alternatives of its own.
        sub_schema: Dict[str, Any] = None
        for sub_schema in all_of:
            if isinstance(sub_schema, dict):
                SlyDataLlmConfigUtil.collect_alternative_groups(sub_schema, groups)
