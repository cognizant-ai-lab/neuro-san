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
                # Accepted so the front man's declared sly_data is available here; not consulted yet.
                llm_config_schema: Dict[str, Any] = None  # pylint: disable=unused-argument
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
        :return: The config with any required api keys replaced, or a set of missing
            required config field names if any required api keys were not provided.
        """
        use_api_keys: Dict[str, str] = {}
        if sly_data is not None and isinstance(sly_data, dict):
            use_api_keys = sly_data.get("llm_config", use_api_keys)

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
                new_value: Any = use_api_keys.get(key)
                if new_value is not None:
                    if isinstance(new_value, str):
                        # Remove leading and trailing whitespace because often these values
                        # are going into http headers which don't like the extra whitespace.
                        new_value = new_value.strip()
                    config[key] = new_value
                else:
                    # Add to the list of complaints about what is missing.
                    required_set.add(key)

        if len(required_set) > 0:
            # We have complaints about what is missing. Return that.
            return required_set

        # We have a nice complete config. Return that.
        return config
