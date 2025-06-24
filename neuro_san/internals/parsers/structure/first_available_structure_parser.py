
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from typing import Any
from typing import Dict
from typing import List

from neuro_san.internals.parsers.structure.structure_parser import StructureParser
from neuro_san.internals.parsers.structure.structure_parser_factory import StructureParserFactory


class FirstAvailableStructureParser(StructureParser):
    """
    StructureParser implementation that takes a list of possible formats
    and does structure parsing on the first one that matches for the text.
    """

    def __init__(self, parse_formats: List[str]):
        """
        Constructor

        :param parse_formats: A List of strings containing potential parse formats to match
        """
        super().__init__()
        self.parse_formats: List[str] = parse_formats
        self.factory = StructureParserFactory()

    def parse_structure(self, content: str) -> Dict[str, Any]:
        """
        Parse the single string content for any signs of structure

        :param content: The string to parse for structure
        :return: A dictionary structure that was embedded in the content.
                Will return None if no parseable structure is detected.
        """
        structure: Dict[str, Any] = None

        for parse_format in self.parse_formats:

            structure_parser: StructureParser = self.factory.create_structure_parser(parse_format)
            if structure_parser is None:
                continue

            structure = structure_parser.parse_structure(content)
            if structure is not None:
                # We only do the first that matches
                self.remainder = structure_parser.get_remainder()
                break

        return structure
