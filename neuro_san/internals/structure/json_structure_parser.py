
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

from json.decoder import JSONDecodeError

from langchain_core.utils.json import parse_json_markdown


class JsonStructureParser:
    """
    JSON implementation for a StructureParser.
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
        # Reset remainder on each call
        self.remainder = None

        meat: str = content
        if "```json" in content:
            # Well-formed json backtick business
            split_header: List[str] = content.split("```json")

            # Start the remainder off with everything before the json backtick business
            self.remainder = split_header[0]

            # Find the end of the backticks if any
            split_footer: List[str] = split_header[-1].split("```")

            # Meat is everything in between
            meat = split_footer[0]

            if len(split_footer) > 1:
                # Add to the remainder anything outside the delimiting backticks
                self.remainder += split_footer[-1]
        
        # Attempt parsing the structure from the meat
        structure: Dict[str, Any] = None
        try:
            structure = parse_json_markdown(meat)
        except JSONDecodeError:
            # Couldn't parse
            self.remainder = None

        # Strip any whitespace of the ends of any remainder.
        if self.remainder is not None:
            self.remainder = self.remainder.strip()

        return structure

    def get_remainder(self) -> str:
        """
        :return: Any content string that was not essential in detecting or
                 describing the structure.  The parse_structure() method must
                 be called to get anything valid out of the return value here.
                 Will return None if no parseable structure is detected.
        """
        return self.remainder
