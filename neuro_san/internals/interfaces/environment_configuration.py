
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

import os


class EnvironmentConfiguration:
    """
    Easy policy add on for the get_value_or_env() method for various classes that
    are effected by configuration via dictionary/hocon and/or environment variables.
    """

    @staticmethod
    def get_value_or_env(config: Dict[str, Any], key: str, env_key: str,
                         none_obj: Any = None) -> Any:
        """
        :param config: The config dictionary to search
        :param key: The key for the config to look for
        :param env_key: The os.environ key whose value should be gotten if either
                        the key does not exist or the value for the key is None
        :param none_obj:  An optional object instance to test.
                          If present this method will return None, implying
                          that some other external object/mechanism is supplying the values.
        """
        if none_obj is not None:
            return None

        value = None
        if config is not None:
            value = config.get(key)

        if value is None and env_key is not None:
            value = EnvironmentConfiguration.getenv(env_key)

        return value

    @staticmethod
    def getenv(env_key: str, default_value: str = None) -> str:
        """
        :param env_key: The os.environ key whose value should be gotten
        :param default_value: default value when the key is not present
        :return: The value of the environment variable which is always a string
        """
        value: str = None
        if env_key is None:
            return value
        value = os.getenv(env_key, default_value) or default_value
        return value
