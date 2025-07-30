
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

import re
from re import Match
from typing import Any
from typing import Dict
from typing import Optional

from json.decoder import JSONDecodeError
from json_repair import loads

from neuro_san.internals.parsers.structure.structure_parser import StructureParser


class JsonStructureParser(StructureParser):
    """
    JSON implementation for a StructureParser.
    """

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
            # Start : End
            "```json": "```",
            "```": "```",
            "`{": "}`",
            "{": "}",
        }

        meat, self.remainder = self._extract_delimited_block(content, delimiters)

        # Attempt parsing the structure from the meat
        structure: Dict[str, Any] = None

        try:
            structure = loads(meat)
            if not isinstance(structure, Dict):
                # json_repair seems to sometimes return an empty string if there is nothing
                # for it to grab onto.
                structure = None
        except JSONDecodeError:
            # Couldn't parse
            self.remainder = None
        except TypeError:
            # meat is None
            self.remainder = None

        return structure

    def _extract_delimited_block(self, text: str, delimiters: Dict[str, str]) -> tuple[Optional[str], str]:
        """
        Extracts a block of text from the input string "text" that is enclosed between any
        of the provided delimiter pairs. Returns a tuple of:
            - The extracted main block with delimiters, or None if no match
            - The remaining string with the block removed and extra whitespace collapsed

        :param text: The input string potentially containing a delimited block
        :param delimiters: A dictionary mapping starting delimiters to ending delimiters

        :return: A tuple of (main block content, remainder string)
        """
        # Try each delimiter pair in order
        for start, end in delimiters.items():
            # Build a regex pattern to find content between start and end delimiters
            # - re.escape ensures special characters like "{" are treated literally
            # - (.*) is a greedy match for any characters between the delimiters
            pattern: str = re.escape(start) + r"(.*)" + re.escape(end)

            # Perform regex search across multiple lines if needed (DOTALL allows "." to match newlines)
            match: Match[str] = re.search(pattern, text, re.DOTALL)

            if match:
                # Extract the matched content (including the delimiters), removing leading/trailing whitespace
                main: str = match.group(0).strip()

                # Remove the matched block (including delimiters) from the input string
                remainder: str = text[:match.start()] + text[match.end():]

                return main, remainder.strip()

        # If no matching delimiters were found, return None and the full cleaned-up input
        return None, text.strip()
