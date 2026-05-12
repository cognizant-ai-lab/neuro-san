
# Copyright (C) 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
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

from logging import getLogger
from logging import Logger

from neuro_san.internals.interfaces.dictionary_validator import DictionaryValidator


class EmptyDictNetworkValidator(DictionaryValidator):
    """
    DictionaryValidator that detects empty dictionaries ({}) in agent network
    configurations. An empty dictionary typically indicates an incomplete or
    erroneous configuration entry.
    """

    def __init__(self):
        """
        Constructor
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    def validate(self, candidate: Dict[str, Any]) -> List[str]:
        """
        Validate the given dictionary by recursively checking for empty
        dictionary values.

        :param candidate: The dictionary to validate
        :return: A list of error messages for each empty dictionary found
        """
        errors: List[str] = []

        if not candidate:
            errors.append("Agent network is empty.")
            return errors

        self._check_empty_dicts(candidate, "", errors)

        if len(errors) > 0:
            self.logger.warning(str(errors))

        return errors

    def _check_empty_dicts(
        self, obj: Any, path: str, errors: List[str]
    ) -> None:
        """
        Recursively walk the configuration and flag any empty dictionaries.

        :param obj: The current object to inspect
        :param path: The dot-separated path to this object in the config
        :param errors: Accumulator for error messages (modified in place)
        """
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path: str = f"{path}.{key}" if path else str(key)
                if isinstance(value, dict) and len(value) == 0:
                    errors.append(
                        f"Empty dictionary found at '{current_path}'."
                    )
                else:
                    self._check_empty_dicts(value, current_path, errors)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                current_path: str = f"{path}[{i}]"
                if isinstance(item, dict) and len(item) == 0:
                    errors.append(
                        f"Empty dictionary found at '{current_path}'."
                    )
                else:
                    self._check_empty_dicts(item, current_path, errors)
