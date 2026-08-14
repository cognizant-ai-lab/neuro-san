
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

import re
from re import Match
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple

from json.decoder import JSONDecodeError
from json_repair import loads

from neuro_san.message.parsers.structure.structure_parser import StructureParser


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

    def _extract_delimited_block(self, text: str, delimiters: Dict[str, str]) -> Tuple[Optional[str], str]:
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
