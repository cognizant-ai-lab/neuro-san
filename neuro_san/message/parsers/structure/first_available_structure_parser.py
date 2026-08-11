
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

from neuro_san.message.parsers.structure.structure_parser import StructureParser
from neuro_san.message.parsers.structure.structure_parser_factory import StructureParserFactory


class FirstAvailableStructureParser(StructureParser):
    """
    StructureParser implementation that takes a list of possible formats
    and does structure parsing on the first one that matches for the text.
    """

    def __init__(self, structure_formats: List[str]):
        """
        Constructor

        :param structure_formats: A List of strings containing potential parse formats to match
        """
        super().__init__()
        self.structure_formats: List[str] = structure_formats
        self.factory = StructureParserFactory()

    def parse_structure(self, content: str) -> Dict[str, Any]:
        """
        Parse the single string content for any signs of structure

        :param content: The string to parse for structure
        :return: A dictionary structure that was embedded in the content.
                Will return None if no parseable structure is detected.
        """
        structure: Dict[str, Any] = None

        for structure_format in self.structure_formats:

            structure_parser: StructureParser = self.factory.create_structure_parser(structure_format)
            if structure_parser is None:
                # Format did not match anything we know how to parse. Keep looking.
                continue

            structure = structure_parser.parse_structure(content)
            if structure is not None:
                # We only do the first that matches
                self.remainder = structure_parser.get_remainder()
                break

        return structure
