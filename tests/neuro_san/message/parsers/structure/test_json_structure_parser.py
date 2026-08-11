
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

from unittest import TestCase

from neuro_san.message.parsers.structure.json_structure_parser import JsonStructureParser


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

    def test_json_backtick_front_remainder(self):
        """
        Tests standard json backtick/markdown in response.
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

    def test_no_backtick_front_remainder(self):
        """
        Tests no backtick/markdown in response.
        """
        test: str = """
This has minimal structure in it.
{
    "key": "value"
}
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value: str = structure.get("key")
        self.assertEqual(value, "value")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "This has minimal structure in it.")

    def test_just_backtick_front_remainder(self):
        """
        Tests no backtick/markdown in response.
        """
        test: str = """
This has minimal structure in it.
```
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

    def test_json_backtick_end_remainder(self):
        """
        Tests standard json backtick/markdown in response.
        """
        test: str = """
```json
{
    "key": "value"
}
```
This has minimal structure in it.
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value: str = structure.get("key")
        self.assertEqual(value, "value")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "This has minimal structure in it.")

    def test_no_backtick_end_remainder(self):
        """
        Tests no backtick/markdown in response.
        """
        test: str = """
{
    "key": "value"
}
This has minimal structure in it.
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value: str = structure.get("key")
        self.assertEqual(value, "value")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "This has minimal structure in it.")

    def test_just_backtick_end_remainder(self):
        """
        Tests no backtick/markdown in response.
        """
        test: str = """
```
{
    "key": "value"
}
```
This has minimal structure in it.
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value: str = structure.get("key")
        self.assertEqual(value, "value")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "This has minimal structure in it.")

    def test_json_backtick_both_remainder(self):
        """
        Tests standard json backtick/markdown in response.
        """
        test: str = """
Here is some JSON:
```json
{
    "key": "value"
}
```
This has minimal structure in it.
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value: str = structure.get("key")
        self.assertEqual(value, "value")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "Here is some JSON:\n\nThis has minimal structure in it.")

    def test_no_backtick_both_remainder(self):
        """
        Tests no backtick/markdown in response.
        """
        test: str = """
Here is some JSON:
{
    "key": "value"
}
This has minimal structure in it.
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value: str = structure.get("key")
        self.assertEqual(value, "value")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "Here is some JSON:\n\nThis has minimal structure in it.")

    def test_just_backtick_both_remainder(self):
        """
        Tests no backtick/markdown in response.
        """
        test: str = """
Here is some JSON:
```
{
    "key": "value"
}
```
This has minimal structure in it.
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value: str = structure.get("key")
        self.assertEqual(value, "value")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "Here is some JSON:\n\nThis has minimal structure in it.")

    def test_json_backtick_no_remainder(self):
        """
        Tests standard json backtick/markdown in response.
        """
        test: str = """
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
        self.assertEqual(remainder, "")

    def test_no_backtick_no_remainder(self):
        """
        Tests no backtick/markdown in response.
        """
        test: str = """
{
    "key": "value"
}
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value: str = structure.get("key")
        self.assertEqual(value, "value")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "")

    def test_just_backtick_no_remainder(self):
        """
        Tests no backtick/markdown in response.
        """
        test: str = """
```
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
        self.assertEqual(remainder, "")

    def test_json_backtick_nested_no_remainder(self):
        """
        Tests standard json backtick/markdown in response.
        """
        test: str = """
```json
{
    "key_1": "value_1",
    "key_2": {
        "key_3": "value_3"
    }
}
```
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value_1: str = structure.get("key_1")
        self.assertEqual(value_1, "value_1")
        value_2: Dict[str, str] = structure.get("key_2")
        self.assertEqual(value_2, {"key_3": "value_3"})
        value_3: str = structure.get("key_2").get("key_3")
        self.assertEqual(value_3, "value_3")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "")

    def test_no_backtick_nested_no_remainder(self):
        """
        Tests no backtick/markdown in response.
        """
        test: str = """
{
    "key_1": "value_1",
    "key_2": {
        "key_3": "value_3"
    }
}
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value_1: str = structure.get("key_1")
        self.assertEqual(value_1, "value_1")
        value_2: Dict[str, str] = structure.get("key_2")
        self.assertEqual(value_2, {"key_3": "value_3"})
        value_3: str = structure.get("key_2").get("key_3")
        self.assertEqual(value_3, "value_3")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "")

    def test_just_backtick_nested_no_remainder(self):
        """
        Tests no backtick/markdown in response.
        """
        test: str = """
```
{
    "key_1": "value_1",
    "key_2": {
        "key_3": "value_3"
    }
}
```
"""
        parser = JsonStructureParser()

        structure: Dict[str, Any] = parser.parse_structure(test)
        self.assertIsNotNone(structure)
        value_1: str = structure.get("key_1")
        self.assertEqual(value_1, "value_1")
        value_2: Dict[str, str] = structure.get("key_2")
        self.assertEqual(value_2, {"key_3": "value_3"})
        value_3: str = structure.get("key_2").get("key_3")
        self.assertEqual(value_3, "value_3")

        remainder: str = parser.get_remainder()
        self.assertIsNotNone(remainder)
        self.assertEqual(remainder, "")
