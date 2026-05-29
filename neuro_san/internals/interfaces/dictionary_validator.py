
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


class DictionaryValidator:
    """
    An interface for validating dictionaries of various meanings.
    """

    def validate(self, candidate: Dict[str, Any]) -> List[str]:
        """
        Validate the given dictionary

        :param candidate: The dictionary to validate
        :return: A list of error messages
        """
        raise NotImplementedError
