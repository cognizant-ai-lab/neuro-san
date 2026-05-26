
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

from neuro_san.internals.interfaces.dictionary_validator import DictionaryValidator


class CompositeDictionaryValidator(DictionaryValidator):
    """
    Implementation of the DictionaryValidator interface that uses multiple validators
    """

    def __init__(self, validators: List[DictionaryValidator], stop_on_error: bool = False):
        """
        Constructor

        :param validators: A list of validators to use
        :param stop_on_error: When True, return after the first validator that produces
                errors instead of running every validator. Useful for ordering phases
                where later validators assume earlier validators passed (e.g., shape
                checks before semantic checks that would crash on malformed input).
                Default False preserves the "collect all errors" behavior.
        """
        self.validators: List[DictionaryValidator] = validators
        self.stop_on_error: bool = stop_on_error

    def validate(self, candidate: Dict[str, Any]) -> List[str]:
        """
        Validate the agent network.

        :param candidate: The dictionary to validate
        :return: A list of error messages
        """
        errors: List[str] = []

        if not candidate:
            errors.append("Nothing to validate.")
            return errors

        if self.validators is None or len(self.validators) == 0:
            errors.append("No validation policy.")
            return errors

        for validator in self.validators:
            new_errors: List[str] = validator.validate(candidate)
            errors.extend(new_errors)
            if new_errors and self.stop_on_error:
                break

        return errors
