
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

from unittest import TestCase

from neuro_san.internals.structure.json_structure_parser import JsonStructureParser


class TestJsonStructureParser(TestCase):
    """
    Unit tests for JsonStructureParser class.
    """

    def test_assumptions(self):
        """
        Can we construct?
        """
        parser = JsonStructureParser()
        self.assertIsNotNone(parser)

    def test_no_structure(self):
        """
        Tests no structure in response.
        """
        test: str = "This has no structure in it"
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNone(structure)
        remainder: str = parser.get_remainder()
        self.assertIsNone(remainder)

    def test_minimal_structure(self):
        """
        Tests no structure in response.
        """
        test: str = """
This has minimal structure in it.
```json
{
    "key": "value"
}
```
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value: str = structure.get("key")
        self.assertEqual(value, "value")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "This has minimal structure in it.")
