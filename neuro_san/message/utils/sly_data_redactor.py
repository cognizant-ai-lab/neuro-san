
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

from leaf_common.config.config_filter import ConfigFilter
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor


class SlyDataRedactor(ConfigFilter):
    """
    An implementation of the ConfigFilter interface which redacts sly data
    based on calling-agent specs.

    Sections of the agent spec that are effected depending on how/where this is
    called are typically:
        * allow.to_downstream.sly_data - filters sly_data sent to external tools
        * allow.from_downstream.sly_data - filters sly_data coming back from external tools
        * allow.to_upstream.sly_data - filters sly_data sent by front-man to client

    Values for these keys can take a variety of forms.
    Most descriptive is a dictionary whose keys are keys to be found
    in the sly_data and whose values are true/false values letting
    that private data through:
        "allow": {
            "to_downstream": {
                "sly_data": {
                    "bearer_token": true,
                    "scratchpad": false,
                }
            }
        }

    This could be shorted to a list form that describes only
    the keys to let through and anything omitted is redacted:
        "allow": {
            "to_downstream": {
                "sly_data": [ "bearer_token" ]
            }
        }

    Something useful for debugging is a boolean value that lets everything through:
        "allow": {
            "to_downstream": {
                "sly_data": true
            }
        }

    But our stance is security by default, so when nothing is listed, it is
    equivalent to this, which lets nothing through:
        "allow": {
            "to_downstream": {
                "sly_data": false
            }
        }

    Finally, an advanced feature of the dictionary form allows for translation
    from one key to another:
        "allow": {
            "to_downstream": {
                "sly_data": {
                    "bearer_token": true,   # let through
                    "secret": "api_key",    # let through, but value from "secret"
                                            # is moved to a new key called "api_key"
                    "scratchpad": false,    # not let through
                }
            }
        }
    """

    def __init__(self, calling_agent_tool_spec: Dict[str, Any],
                 config_keys: List[str] = None,
                 allow_empty_dict: bool = True):
        """
        Constructor

        :param calling_agent_tool_spec: The dictionary describing the JSON agent tool
                            that is providing the sly_data.
        :param config_keys: A list of config keys in reverse precedence order.
                    That is, the further on in the list you get, the greater the precedence.
                    Each string is a fully qualified identifier that can span multiple
                    dictionaries like: "allow.to_upstream.sly_data".
        :param allow_empty_dict: Default is true which allows filter_config() to return
                    an empty dictionary.  When set to False and empty this yields
                    a None value.
        """
        self.agent_tool_spec: Dict[str, Any] = calling_agent_tool_spec
        self.config_keys: List[str] = config_keys
        if self.config_keys is None:
            self.config_keys = []
        self.allow_empty_dict: bool = allow_empty_dict

    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param basis_config: Source of the sly_data to redact.
        :return: A new sly_data dictionary with proper redactions per the config_keys on the
                agent_tool_spec.  If no such keys exist, then no sly_data
                gets through to the agent to be called.  Also, if allow_empty_dict
                is set to true, this method can return an empty dictionary.
                When allow_empty_dict is set to False and empty dictionary returns a None value.
        """
        empty: Dict[str, Any] = {}

        extractor = DictionaryExtractor(self.agent_tool_spec)

        # Find the right dictionary given the configured config_keys.
        allow_dict: Dict[str, Any] = empty
        for config_key in self.config_keys:
            allow_dict = extractor.get(config_key, allow_dict)

        # Recall empty dictionaries evaluate to False (as well as boolean values)
        if not bool(allow_dict):
            # By default we don't let anything through
            return self.maybe_empty(empty)

        if isinstance(allow_dict, bool) and bool(allow_dict):
            # The value is a simple True, so let everything through.
            return self.maybe_empty(basis_config)

        if not bool(basis_config) or not isinstance(basis_config, Dict):
            # There is no dictionary content, so nothing to redact
            return self.maybe_empty(empty)

        if isinstance(allow_dict, List):
            # What was configured was a list.
            # Turn the string keys listed into a dictionary for canonical processing below.
            true_dict: Dict[str, Any] = {}
            for key in allow_dict:
                true_dict[key] = True
            allow_dict = true_dict

        # Got rid of all the easy cases.
        # Now leaf through the keys of the dictionaries.
        # For now, just do top-level keys. Can get more complicated later if need be.
        redacted: Dict[str, Any] = {}
        for source_key, dest_key in allow_dict.items():

            source_value: Any = basis_config.get(source_key)
            if source_value is None:
                # We have an allowance, but no data, so nothing to do for this key.
                continue

            if isinstance(dest_key, str):
                # Translate the key
                redacted[dest_key] = source_value
            elif isinstance(dest_key, bool) and bool(dest_key):
                # Use the same key and the same value in the explicit allow
                redacted[source_key] = source_value

        return self.maybe_empty(redacted)

    def maybe_empty(self, test_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param test_dict: The dictionary to test for emptiness
        :return: If the test_dict is empty and the instance is not configured
                to return empty dictionaries, then return None. Otherise return
                the test_dict in its entirety
        """
        # Recall empty dictionaries evaluate to False
        if not self.allow_empty_dict and not bool(test_dict):
            return None
        return test_dict
