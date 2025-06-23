
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
        delimiters: Dict[str, str] = {
            "```json":  {
                "end": "```",
                "use_delims": True
            },
            "```":  {
                "end": "```",
                "use_delims": False
            },
            "{":  {
                "end": "}",
                "use_delims": True
            }
        }

        for start_delim, parse_dict in delimiters.items():
            if start_delim in content:
                # Well-formed per delimiter
                split_header: List[str] = content.split(start_delim)

                # Start the remainder off with everything before the json backtick business
                self.remainder = split_header[0]

                # Find the end of the backticks if any
                end_delim: str = parse_dict.get("end")
                if end_delim != start_delim:
                    split_footer: List[str] = split_header[-1].split(end_delim)
                    meat = split_footer[0]
                    if len(split_footer) > 1:
                        # Add to the remainder anything outside the delimiting backticks
                        self.remainder += split_footer[-1]
                else:
                    meat = split_header[1]
                    if len(split_header) > 2:
                        # Add the remaining with the end delimiter.
                        # We are only parsing the first we find.
                        self.remainder += end_delim.join(split_header[2:])

                # Meat is everything in between, maybe with start and end delims on either end.
                meat = meat.strip()
                if parse_dict.get("use_delims", True):
                    meat = f"{start_delim}{meat}{end_delim}"

                break

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
