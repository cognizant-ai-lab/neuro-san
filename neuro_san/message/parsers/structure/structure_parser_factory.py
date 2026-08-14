
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

from neuro_san.message.parsers.structure.json_structure_parser import JsonStructureParser
from neuro_san.message.parsers.structure.structure_parser import StructureParser


class StructureParserFactory:
    """
    Factory for creating StructureParser instances based on a string type
    """

    def create_structure_parser(self, parser_type: str) -> StructureParser:
        """
        Creates a structure parser given the string type

        :param parser_type: A string describing the format of the structure parser.
        """

        structure_parser: StructureParser = None

        if parser_type is None or not isinstance(parser_type, str):
            structure_parser = None
        elif parser_type.lower() == "json":
            structure_parser = JsonStructureParser()

        return structure_parser
