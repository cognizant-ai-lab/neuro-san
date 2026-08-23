
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


class StructureParser:
    """
    Interface that allows parsing a dictionary from within LLM response text.
    Concrete subclasses implement parsing from various formats.

    The notion of a "remainder" allows for communicating other descriptive text
    outside of what was parsed for the dictionary itself.
    """

    def __init__(self):
        """
        Constructor
        """
        self.remainder: str = None

    def parse_structure(self, content: str) -> Dict[str, Any]:
        """
        Parse the single string content for any signs of structure

        :param content: The string to parse for structure
        :return: A dictionary structure that was embedded in the content.
                Will return None if no parseable structure is detected.
        """
        raise NotImplementedError

    def get_remainder(self) -> str:
        """
        :return: Any content string that was not essential in detecting or
                 describing the structure.  The parse_structure() method must
                 be called to get anything valid out of the return value here.
                 Will return None if no parseable structure is detected.
        """
        return self.remainder
