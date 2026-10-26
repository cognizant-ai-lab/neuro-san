
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

from leaf_common.utils.environment_util import EnvironmentUtil as Env


class TranslateOptions:
    """
    Utility class for translating keyword arguments from a few dictionaries and sets.
    This is used largely for TypeScript translations.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, renamed: Dict[str, str] = None,
                 nested: Dict[str, str] = None,
                 nest_to: str = None,
                 dropped: Set[str] = None,
                 options_key_to_env_var: Dict[str, str] = None,
                 nested_key_to_env_var: Dict[str, str] = None):
        """
        Constructor

        :param renamed: The renamed fields
        :param nested: The nested fields
        :param nest_to: The options field that the nested fields nest to
        :param dropped: The dropped fields
        :param options_key_to_env_var: The options key to env var
        :param nested_key_to_env_var: The configuration key to env var
        """
        self.renamed: Dict[str, str] = renamed
        if self.renamed is None:
            self.renamed = {}

        self.nested: Dict[str, str] = nested
        if self.nested is None:
            self.nested = {}

        self.nest_to: str = nest_to

        self.dropped: Set[str] = dropped
        if self.dropped is None:
            self.dropped = set()

        self.options_key_to_env_var: Dict[str, str] = options_key_to_env_var
        if self.options_key_to_env_var is None:
            self.options_key_to_env_var = {}

        self.nested_key_to_env_var: Dict[str, str] = nested_key_to_env_var
        if self.nested_key_to_env_var is None:
            self.nested_key_to_env_var = {}

    @staticmethod
    def is_set(value: Any) -> bool:
        """
        Check if the value is set
        :param value: The value to check
        :return: True if the value is set. False otherwise.
        """
        if value is None:
            return False

        value_str: str = str(value)
        if value_str == "":
            return False

        return True

    def translate(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Do the translation

        :param kwargs: The keyword arguments
        :return: The translated keyword arguments
        """

        use_kwargs: Dict[str, Any] = kwargs
        if use_kwargs is None:
            use_kwargs = {}

        options: Dict[str, Any] = {}
        nested_dict: Dict[str, Any] = {}

        key: str = None
        value: Any = None
        for key, value in use_kwargs.items():

            if key in self.dropped or not TranslateOptions.is_set(value):
                continue

            nested_key: str = self.nested.get(key)
            if nested_key:
                nested_dict[nested_key] = value
                continue

            renamed_key: str = self.renamed.get(key)
            if renamed_key:
                options[renamed_key] = value

            # Anything else is a python-only argument, and dropping it is the point.

        options = self.translate_dict_from_env(options, self.options_key_to_env_var)
        nested_dict = self.translate_dict_from_env(nested_dict, self.nested_key_to_env_var)
        if len(nested_dict.keys()) > 0:
            options[self.nest_to] = nested_dict

        return options

    @staticmethod
    def translate_dict_from_env(source: Dict[str, Any], key_to_env_var: Dict[str, str]) -> Dict[str, Any]:
        """
        Potentially add missing values to a dictionary from environment vars.

        :param source: The source dictionary
        :param key_to_env_var: The key to env var mapping
        :return: The translated dictionary
        """
        # Loop through the source and set any unset values from the env,
        # based on the key_to_env_var mapping, as long as the env var is set too.
        env_var_name: str = None
        for key, env_var_name in key_to_env_var.items():
            value = source.get(key)
            if not TranslateOptions.is_set(value):
                value = Env.getenv(env_var_name)
                if TranslateOptions.is_set(value):
                    source[key] = value

        return source
