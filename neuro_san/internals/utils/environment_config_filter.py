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
from typing import Union

from os import environ

from leaf_common.config.config_filter import ConfigFilter


class EnvironmentConfigFilter(ConfigFilter):
    """
    ConfigFilter implementation which takes nested dictionaries,
    whose leaf keys are environment variable keys, and whose leaf values are defaults
    to use when looking up those env vars.
    """

    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filters the given basis config.

        If the value for any key is a dictionary, recurse with that value as the basis.
        Any other value is taken as the default for an environment variable lookup
        against the key. The default applies only when the variable is absent;
        a variable that is set to an empty string keeps its empty value.

        :param basis_config: The config dictionary to act as the basis
                for filtering
        :return: A config dictionary, potentially modified as per the
                policy encapsulated by the implementation
        """
        return_dict: Dict[str, Any] = {}

        key: str = None
        value: Union[str, Dict[str, Any]] = None
        for key, value in basis_config.items():

            if isinstance(value, dict):
                value_dict: Dict[str, Any] = value
                value_dict = self.filter_config(value_dict)
                return_dict[key] = value_dict
            else:
                value_str: str = value
                # Not EnvironmentUtil.getenv(), which also replaces an empty value with the default.
                value_str = environ.get(key, value_str)
                return_dict[key] = value_str

        return return_dict
