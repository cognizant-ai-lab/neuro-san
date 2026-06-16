
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


class ConfigUtil:
    """
    Utilities for reading values out of config dictionaries with the kind
    of forgiving type-coercion that HOCON / JSON / env-derived configs
    tend to require in practice.
    """

    @staticmethod
    # pylint: disable=too-many-return-statements
    def get_bool(config: Dict[str, Any], key: str, default: bool = False) -> bool:
        """
        Read a boolean-valued config entry, accepting common boolean-like
        forms found in configs sourced from HOCON, JSON, or environment
        variables.

        Recognized inputs:
          - bool: returned as-is.
          - str: case-insensitive match against "true"/"yes" -> True;
                 case-insensitive match against "false"/"no" -> False.
          - int: 0 -> False, any other int -> True. (Note: bool is checked
                 first; Python's True/False would otherwise match the int
                 branch since bool is a subclass of int.)

        When the key is absent OR the value is present but not in one of
        the recognized forms (e.g. None, list, dict, an unrecognized
        string), the supplied `default` is returned. This makes the helper
        safe to call against partially-specified configs without having to
        pre-validate them.

        :param config: The config dict to read from.
        :param key: The key whose value should be interpreted as a bool.
        :param default: The value to return when the key is missing or its
                        value is not a recognized boolean-like form.
        :return: The boolean interpretation of config[key], or default.
        """
        if key not in config:
            return default
        value: Any = config[key]
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "yes"):
                return True
            if lowered in ("false", "no"):
                return False
            return default
        if isinstance(value, int):
            return value != 0
        return default
